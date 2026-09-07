"""
Tests para /api/chat — SSE streaming.

F08 contract (preserved byte-for-byte):
  - request model ``ChatRequest``
  - ``event: sources`` first
  - ``event: token`` for chunks
  - ``event: done`` last on success
  - ``event: error`` last on failure
  - HTTP 400/401/404/409 paths unchanged

F11 additions (issue #13, design.md §13):
  - ``event: tool_start`` / ``event: tool_end`` pairs (REQ-7 / SCN-1)
  - ``event: degraded`` between sources and first token on Context7
    unavailability (REQ-6 / SCN-3)
  - No tool events on the RAG-only path (SCN-2)
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Existing F08 surface (preserved)
# ---------------------------------------------------------------------------


class TestChatRequestModel:
    """Tests del model de request de chat."""

    def test_chat_request_with_project(self):
        from app.api.chat import ChatRequest

        req = ChatRequest(project_id=1, message="Hello world")
        assert req.project_id == 1
        assert req.message == "Hello world"

    def test_chat_request_without_project(self):
        from app.api.chat import ChatRequest

        req = ChatRequest(project_id=None, message="Hello")
        assert req.project_id is None
        assert req.message == "Hello"

    def test_chat_request_allows_empty_message_at_model_level(self):
        """Pydantic accepts any string; content validation is in the endpoint."""
        from app.api.chat import ChatRequest

        # ChatRequest accepts empty/whitespace strings at model level
        req = ChatRequest(project_id=None, message="")
        assert req.message == ""

        req2 = ChatRequest(project_id=None, message="   ")
        assert req2.message == "   "

    def test_chat_request_normal_message(self):
        from app.api.chat import ChatRequest

        req = ChatRequest(project_id=1, message="Diseña un sistema de login")
        assert req.project_id == 1
        assert req.message == "Diseña un sistema de login"


class TestSSEStreamCallbackHandler:
    """Tests del handler de streaming SSE."""

    @patch("app.api.sse.asyncio.Queue")
    def test_handler_initialization(self, mock_queue):
        from app.api.sse import SSEStreamCallbackHandler

        handler = SSEStreamCallbackHandler()
        assert handler._done is False
        assert len(handler._errors) == 0


class TestChatEndpointErrors:
    """Tests de errores del endpoint de chat (lógica sin red)."""

    def test_llm_config_error_exists(self):
        """LLMConfigError is raised when user has no LLM config."""
        from app.core.llm_loader import LLMConfigError

        err = LLMConfigError("Usuario no tiene config LLM")
        assert "config LLM" in str(err)


class TestSSEFormat:
    """Tests del formato SSE emitido por el endpoint."""

    def test_sse_token_event_format(self):
        token = "Hola"
        formatted = f"event: token\ndata: {json.dumps(token, ensure_ascii=False)}\n\n"
        assert "event: token" in formatted
        assert "Hola" in formatted

    def test_sse_done_event_format(self):
        formatted = f"event: done\ndata: null\n\n"
        assert formatted == "event: done\ndata: null\n\n"

    def test_sse_error_event_format(self):
        error_msg = "Connection timeout"
        formatted = f"event: error\ndata: {json.dumps(error_msg, ensure_ascii=False)}\n\n"
        assert "event: error" in formatted
        assert "Connection timeout" in formatted


class TestJWTAuth:
    """Tests de JWT auth (sin HTTP)."""

    def test_create_and_verify_token(self):
        from app.core.jwt import create_access_token, verify_token

        token = create_access_token(user_id=42, username="architect")
        payload = verify_token(token)
        assert payload["sub"] == "42"
        assert payload["username"] == "architect"

    def test_expired_token_raises(self):
        from datetime import timedelta
        from app.core.jwt import create_access_token, verify_token, JWTError

        # Create token that expires immediately
        token = create_access_token(
            user_id=1, username="test", expires_delta=timedelta(seconds=-1)
        )
        with pytest.raises(JWTError) as exc_info:
            verify_token(token)
        assert "expired" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# F11 integration — drive the event_generator through patched ``run_agent``
# ---------------------------------------------------------------------------


def _drain(generator) -> list[str]:
    """Run the async generator to completion and return its string payloads."""
    async def _drive():
        return [chunk async for chunk in generator]

    return asyncio.run(_drive())


def _make_run_agent_mock(events):
    """Return a coroutine that yields ``events`` then stops."""
    async def _fake_run_agent(*_args, **kwargs):
        for ev in events:
            yield ev

    return _fake_run_agent


def _empty_rag_doc():
    """Return an empty list of RAG documents."""
    return []


def _sources_event(sources):
    return f"event: sources\ndata: {json.dumps(sources, ensure_ascii=False)}\n\n"


def _tool_start(name):
    return f"event: tool_start\ndata: {json.dumps({'tool': name}, ensure_ascii=False)}\n\n"


def _tool_end(name, status="ok", result_length=0, latency_ms=0):
    payload = {
        "tool": name,
        "result_length": result_length,
        "latency_ms": latency_ms,
        "status": status,
    }
    return f"event: tool_end\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _token(text):
    return f"event: token\ndata: {json.dumps(text, ensure_ascii=False)}\n\n"


def _done():
    return "event: done\ndata: null\n\n"


def _degraded(reason="context7_timeout", source="context7", fallback="rag_only"):
    payload = {"source": source, "reason": reason, "fallback": fallback}
    return f"event: degraded\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _error(message):
    return f"event: error\ndata: {json.dumps(message, ensure_ascii=False)}\n\n"


def _patch_chat_route(*, rag_docs=None, run_agent_events=None, ordering=None):
    """Patch ``build_langchain_model``, ``similarity_search`` and ``run_agent``.

    Returns a list of patches applied so the caller can pop them in teardown.
    """
    from app.api import chat as chat_module

    rag_docs = rag_docs if rag_docs is not None else _empty_rag_doc()

    patches = []

    # Build a fake model.
    fake_model = MagicMock(name="fake-model")
    fake_model.model_name = "fake-model"

    p_model = patch.object(
        chat_module, "build_langchain_model", return_value=fake_model
    )
    patches.append(p_model)

    p_rag = patch.object(
        chat_module,
        "similarity_search",
        return_value=(rag_docs, {"embedding_ms": 0, "search_ms": 0, "total_ms": 0}),
    )
    patches.append(p_rag)

    if run_agent_events is not None:
        p_run = patch.object(
            chat_module, "run_agent", side_effect=_make_run_agent_mock(run_agent_events)
        )
        patches.append(p_run)

    p_lf = patch.object(chat_module, "get_langfuse_handler", return_value=None)
    patches.append(p_lf)

    # F12 persistence collaborators: the pre-done persistence block must
    # never touch a real Postgres or Engram in unit tests. When ``ordering``
    # is a list, side effects append to it so tests can assert ordering.
    mock_db = MagicMock(name="fake-db")
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)
    mock_db.execute.return_value.scalar.return_value = 1  # liveness probe
    patches.append(patch.object(chat_module, "SessionLocal", return_value=mock_db))
    patches.append(patch.object(chat_module, "ensure_user_session", return_value=1))
    patches.append(
        patch.object(
            chat_module,
            "save_message",
            side_effect=lambda _db, **_kw: MagicMock(id=99),
        )
    )
    if ordering is None:
        patches.append(patch.object(chat_module, "engram_mirror", return_value=None))
    else:
        mock_db.commit.side_effect = lambda: ordering.append("commit")
        patches.append(
            patch.object(
                chat_module,
                "engram_mirror",
                side_effect=lambda *_a, **_kw: ordering.append("engram_mirror"),
            )
        )

    return patches


async def _call_chat(chat_module, body, current_user):
    """Await the chat route function (it's ``async def``)."""
    return await chat_module.chat(body=body, current_user=current_user)


async def _drive_event_generator(generator):
    """Async drain an async generator into a list."""
    out = []
    async for chunk in generator:
        out.append(chunk)
        if len(out) > 64:
            break
    return out


def _run_chat(chat_module, body, current_user):
    """Coroutine: call the chat route and return its ``StreamingResponse``."""
    return _call_chat(chat_module, body, current_user)


# ---------------------------------------------------------------------------
# SCN-1: tools get called -> sources, tool_start, tool_end, tokens, done
# ---------------------------------------------------------------------------


def test_chat_stream_emits_tool_start_then_tool_end_then_tokens_then_done(monkeypatch):
    """SCN-1 happy path with two tool invocations."""
    from app.api import chat as chat_module

    patches = _patch_chat_route(
        run_agent_events=[
            {"event": "tool_start", "data": {"tool": "resolve-library-id"}},
            {"event": "tool_end", "data": {"tool": "resolve-library-id",
                                            "result_length": 18,
                                            "latency_ms": 12,
                                            "status": "ok"}},
            {"event": "token", "data": "Hola"},
            {"event": "done", "data": None},
        ],
    )
    for p in patches:
        p.start()

    try:
        body = chat_module.ChatRequest(message="como configuro retries en requests?")
        current_user = {"user_id": 1, "username": "architect"}

        async def _drive():
            response = await _call_chat(chat_module, body, current_user)
            return await _drive_event_generator(response.body_iterator)

        chunks = asyncio.run(_drive())
        body_text = "".join(chunks)
        # Sources first.
        assert body_text.startswith(_sources_event([]))
        # Then tool_start, tool_end, token, done.
        assert _tool_start("resolve-library-id") in body_text
        idx_start = body_text.find(_tool_start("resolve-library-id"))
        idx_end = body_text.find(_tool_end("resolve-library-id", result_length=18, latency_ms=12))
        idx_token = body_text.find(_token("Hola"))
        idx_done = body_text.find(_done())
        assert 0 <= idx_start < idx_end < idx_token < idx_done
    finally:
        for p in patches:
            p.stop()


# ---------------------------------------------------------------------------
# SCN-2: RAG-only path (no tool events)
# ---------------------------------------------------------------------------


def test_chat_stream_emits_no_tool_events_when_rag_only(monkeypatch):
    """SCN-2: when no tools are invoked, only sources + tokens + done appear."""
    from app.api import chat as chat_module

    patches = _patch_chat_route(
        run_agent_events=[
            {"event": "token", "data": "Directo desde el RAG."},
            {"event": "done", "data": None},
        ],
    )
    for p in patches:
        p.start()

    try:
        body = chat_module.ChatRequest(message="explica el patron saga")
        current_user = {"user_id": 2, "username": "architect"}

        async def _drive():
            response = await _call_chat(chat_module, body, current_user)
            return await _drive_event_generator(response.body_iterator)

        chunks = asyncio.run(_drive())
        body_text = "".join(chunks)
        assert "event: tool_start" not in body_text
        assert "event: tool_end" not in body_text
        assert "event: degraded" not in body_text
        assert "Directo desde el RAG." in body_text
        assert body_text.endswith(_done())
    finally:
        for p in patches:
            p.stop()


# ---------------------------------------------------------------------------
# SCN-3: degraded event appears between sources and the first token
# ---------------------------------------------------------------------------


def test_chat_stream_emits_degraded_event_between_sources_and_tokens(monkeypatch):
    """REQ-6 / SCN-3: degraded event is emitted exactly once and before tokens."""
    from app.api import chat as chat_module

    patches = _patch_chat_route(
        run_agent_events=[
            {"event": "degraded", "data": {"source": "context7",
                                            "reason": "context7_timeout",
                                            "fallback": "rag_only"}},
            {"event": "token", "data": "Respuesta sin librerias."},
            {"event": "done", "data": None},
        ],
    )
    for p in patches:
        p.start()

    try:
        body = chat_module.ChatRequest(message="ayuda")
        current_user = {"user_id": 3, "username": "architect"}

        async def _drive():
            response = await _call_chat(chat_module, body, current_user)
            return await _drive_event_generator(response.body_iterator)

        chunks = asyncio.run(_drive())
        body_text = "".join(chunks)

        idx_sources = body_text.find("event: sources")
        idx_degraded = body_text.find(_degraded(reason="context7_timeout"))
        idx_token = body_text.find(_token("Respuesta sin librerias."))
        idx_done = body_text.find(_done())

        assert 0 <= idx_sources < idx_degraded < idx_token < idx_done
        # Exactly one degraded event.
        assert body_text.count("event: degraded\n") == 1
    finally:
        for p in patches:
            p.stop()


# ---------------------------------------------------------------------------
# F11 wiring — Langfuse handler is appended when present, skipped otherwise
# ---------------------------------------------------------------------------


def test_chat_route_passes_langfuse_handler_when_env_set(monkeypatch):
    from app.api import chat as chat_module

    captured = {}

    def _fake_get_langfuse_handler():
        captured["called"] = True
        return MagicMock(name="langfuse-handler")

    patches = _patch_chat_route(
        run_agent_events=[{"event": "done", "data": None}],
    )
    patches.append(patch.object(chat_module, "get_langfuse_handler",
                                 side_effect=_fake_get_langfuse_handler))

    for p in patches:
        p.start()

    try:
        body = chat_module.ChatRequest(message="hi")
        current_user = {"user_id": 4, "username": "architect"}
        captured_callbacks = {}

        async def _capture_run_agent(*args, **kwargs):
            captured_callbacks["callbacks"] = kwargs.get("callbacks")
            if False:  # pragma: no cover
                yield {}

        with patch.object(chat_module, "run_agent", side_effect=_capture_run_agent):

            async def _drive():
                response = await _call_chat(chat_module, body, current_user)
                await _drive_event_generator(response.body_iterator)

            asyncio.run(_drive())

        assert captured.get("called") is True
        callbacks = captured_callbacks.get("callbacks") or []
        assert any(getattr(c, "_mock_name", "") == "langfuse-handler" for c in callbacks)
    finally:
        for p in patches:
            p.stop()


def test_chat_route_skips_langfuse_handler_when_env_unset(monkeypatch):
    """REQ-5 / SCN-6: ``None`` handler leaves the callback list at SSE only."""
    from app.api import chat as chat_module

    captured_callbacks = {}

    async def _capture_run_agent(*args, **kwargs):
        captured_callbacks["callbacks"] = kwargs.get("callbacks")
        if False:  # pragma: no cover
            yield {}

    patches = _patch_chat_route(run_agent_events=[{"event": "done", "data": None}])
    for p in patches:
        p.start()

    try:
        body = chat_module.ChatRequest(message="hi")
        current_user = {"user_id": 5, "username": "architect"}
        with patch.object(chat_module, "run_agent", side_effect=_capture_run_agent):

            async def _drive():
                response = await _call_chat(chat_module, body, current_user)
                await _drive_event_generator(response.body_iterator)

            asyncio.run(_drive())

        callbacks = captured_callbacks.get("callbacks") or []
        assert len(callbacks) == 1
        from app.api.sse import SSEStreamCallbackHandler
        assert isinstance(callbacks[0], SSEStreamCallbackHandler)
    finally:
        for p in patches:
            p.stop()


# ---------------------------------------------------------------------------
# Error handling — inner ``error`` event terminates the stream cleanly
# ---------------------------------------------------------------------------


def test_chat_route_terminates_on_inner_error_event(monkeypatch):
    """``run_agent`` yielding ``error`` must surface as the final SSE event."""
    from app.api import chat as chat_module

    patches = _patch_chat_route(
        run_agent_events=[
            {"event": "token", "data": "partial"},
            {"event": "error", "data": "boom"},
        ],
    )
    for p in patches:
        p.start()

    try:
        body = chat_module.ChatRequest(message="hi")
        current_user = {"user_id": 6, "username": "architect"}

        async def _drive():
            response = await _call_chat(chat_module, body, current_user)
            return await _drive_event_generator(response.body_iterator)

        chunks = asyncio.run(_drive())
        body_text = "".join(chunks)
        assert "partial" in body_text
        assert "boom" in body_text
        assert body_text.count("event: done\n") == 0
        assert body_text.count("event: error\n") == 1
        assert body_text.endswith(_error("boom"))
    finally:
        for p in patches:
            p.stop()


def test_chat_route_fires_done_when_run_agent_omits_it(monkeypatch):
    """Defensive: if ``run_agent`` returns without ``done``, the route emits it."""
    from app.api import chat as chat_module

    patches = _patch_chat_route(
        run_agent_events=[
            {"event": "token", "data": "alone"},
        ],
    )
    for p in patches:
        p.start()

    try:
        body = chat_module.ChatRequest(message="hi")
        current_user = {"user_id": 7, "username": "architect"}

        async def _drive():
            response = await _call_chat(chat_module, body, current_user)
            return await _drive_event_generator(response.body_iterator)

        chunks = asyncio.run(_drive())
        body_text = "".join(chunks)
        assert body_text.endswith(_done())
    finally:
        for p in patches:
            p.stop()


# ---------------------------------------------------------------------------
# HTTP headers preserved byte-for-byte (F08 contract)
# ---------------------------------------------------------------------------


def test_chat_response_preserves_sse_headers(monkeypatch):
    from app.api import chat as chat_module

    patches = _patch_chat_route(run_agent_events=[{"event": "done", "data": None}])
    for p in patches:
        p.start()

    try:
        body = chat_module.ChatRequest(message="hi")
        current_user = {"user_id": 8, "username": "architect"}

        async def _drive():
            return await _call_chat(chat_module, body, current_user)

        response = asyncio.run(_drive())
        assert response.media_type == "text/event-stream"
        assert response.headers["Cache-Control"] == "no-cache"
        assert response.headers["X-Accel-Buffering"] == "no"
    finally:
        for p in patches:
            p.stop()


# ---------------------------------------------------------------------------
# RAG sources event shape preserved
# ---------------------------------------------------------------------------


def test_chat_stream_sources_event_carries_doc_metadata(monkeypatch):
    from app.api import chat as chat_module

    doc = MagicMock()
    doc.page_content = "saga body"
    doc.metadata = {
        "source_type": "architect_pattern",
        "pattern_name": "Saga",
        "similarity": 0.92,
    }

    patches = _patch_chat_route(
        rag_docs=[doc],
        run_agent_events=[{"event": "done", "data": None}],
    )
    for p in patches:
        p.start()

    try:
        body = chat_module.ChatRequest(message="explica saga")
        current_user = {"user_id": 9, "username": "architect"}

        async def _drive():
            response = await _call_chat(chat_module, body, current_user)
            return await _drive_event_generator(response.body_iterator)

        chunks = asyncio.run(_drive())
        body_text = "".join(chunks)
        sources_line = next(
            line for line in body_text.split("\n\n") if line.startswith("event: sources")
        )
        sources_payload = json.loads(sources_line.split("data: ", 1)[1])
        assert sources_payload == [
            {"source_type": "architect_pattern", "name": "Saga", "similarity": 0.92}
        ]
    finally:
        for p in patches:
            p.stop()


# ---------------------------------------------------------------------------
# F12 persistence on the merged F11 run_agent flow (merge integration)
# ---------------------------------------------------------------------------


def test_f12_commit_happens_before_done_on_agent_flow():
    """Merge invariant: F12 REQ-4 survives the F11 run_agent flow.

    Drives the REAL event_generator (patched collaborators) and records, in
    real time, the commit, the Engram mirror and every yielded chunk. The
    commit must land BEFORE the ``event: done`` chunk is produced.
    """
    from app.api import chat as chat_module

    ordering: list[str] = []

    patches = _patch_chat_route(
        run_agent_events=[
            {"event": "token", "data": "Hola"},
            {"event": "done", "data": None},
        ],
        ordering=ordering,
    )
    for p in patches:
        p.start()

    try:
        body = chat_module.ChatRequest(message="hola")
        current_user = {"user_id": 1, "username": "architect"}

        async def _drive():
            response = await _call_chat(chat_module, body, current_user)
            async for chunk in response.body_iterator:
                ordering.append(chunk)

        asyncio.run(_drive())
    finally:
        for p in patches:
            p.stop()

    done_idx = next(
        i for i, item in enumerate(ordering)
        if isinstance(item, str) and item.startswith("event: done")
    )
    assert ordering.index("commit") < done_idx
    assert ordering.index("commit") < ordering.index("engram_mirror")


def test_f12_persistence_failure_on_done_yields_error_not_done():
    """Merge invariant: if the persistence tx fails at done-time, the stream
    terminates with ``event: error`` and never emits ``event: done``."""
    from app.api import chat as chat_module
    from sqlalchemy.exc import SQLAlchemyError

    mock_db = MagicMock(name="failing-db")
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)
    mock_db.execute.return_value.scalar.return_value = 1  # liveness probe OK
    mock_db.commit.side_effect = SQLAlchemyError("insert failed")

    patches = _patch_chat_route(
        run_agent_events=[
            {"event": "token", "data": "Hola"},
            {"event": "done", "data": None},
        ],
    )
    # Override the default (successful) persistence mocks with a failing tx.
    patches.append(patch.object(chat_module, "SessionLocal", return_value=mock_db))
    patches.append(patch.object(chat_module, "ensure_user_session", return_value=1))
    patches.append(
        patch.object(
            chat_module,
            "save_message",
            side_effect=lambda _db, **_kw: MagicMock(id=1),
        )
    )
    patches.append(patch.object(chat_module, "engram_mirror", return_value=None))

    for p in patches:
        p.start()

    try:
        body = chat_module.ChatRequest(message="hola")
        current_user = {"user_id": 1, "username": "architect"}

        async def _drive():
            response = await _call_chat(chat_module, body, current_user)
            return await _drive_event_generator(response.body_iterator)

        chunks = asyncio.run(_drive())
    finally:
        for p in patches:
            p.stop()

    body_text = "".join(chunks)
    assert "event: error" in body_text
    assert "event: done" not in body_text


# ---------------------------------------------------------------------------
# F12.2 (ported onto the merged flow): SCN-1, SCN-4, SCN-7 — commit-before-
# yield + Engram-down resilience, replicated inline (no Postgres needed).
# ---------------------------------------------------------------------------


class TestEventGeneratorPersistence:
    """F12.2: SCN-1, SCN-4, SCN-7 — commit-before-yield + Engram-down resilience.

    We replicate the persistence block inline rather than instantiating the
    FastAPI app — the goal is to assert the orchestration contract (commit
    happens BEFORE the 'done' yield; EngramError does not abort the stream)
    without spinning up Postgres.
    """

    @staticmethod
    def _run_persistence_block(
        *,
        session,
        engram_mirror,
        user_msg_content: str,
        assistant_content: str,
        user_id: int,
        project_id,
        ordering: list[str],
    ):
        """Mimic the chat route's pre-``done`` persistence block."""
        from app.models.message import Message

        session.add(
            Message(
                role="user",
                user_id=user_id,
                project_id=project_id,
                session_id=1,
                content=user_msg_content,
            )
        )
        session.add(
            Message(
                role="assistant",
                user_id=user_id,
                project_id=project_id,
                session_id=1,
                content=assistant_content,
                citations=[],
            )
        )
        session.commit()
        ordering.append("commit")
        try:
            engram_mirror("u", user_id=user_id, project_id=project_id)
            engram_mirror("a", user_id=user_id, project_id=project_id)
        except Exception:
            # Must NOT propagate — REQ-6 / REQ-10 / SCN-4.
            pass

    def test_commit_happens_before_done_yield(self):
        """REQ-4 / SCN-1 / SCN-7: ordering invariant."""
        ordering: list[str] = []

        session = MagicMock()
        # Track commit vs yield-done ordering.

        # Patch engram_mirror where chat.py imports it.
        with patch("app.api.chat.engram_mirror") as fake_mirror:
            fake_mirror.side_effect = lambda *_a, **_kw: ordering.append("engram_mirror")

            # Build a tiny async generator that yields tokens then runs the
            # persistence block then yields 'done'.
            async def run():
                yield "event: sources\ndata: []\n\n"
                yield "event: token\ndata: \"hi\"\n\n"
                self._run_persistence_block(
                    session=session,
                    engram_mirror=fake_mirror,
                    user_msg_content="hola",
                    assistant_content="hi",
                    user_id=1,
                    project_id=1,
                    ordering=ordering,
                )
                ordering.append("yield_done")
                yield "event: done\ndata: null\n\n"

            _drain(run())

        assert ordering.index("commit") < ordering.index("yield_done")
        # And engram_mirror fires after commit.
        assert ordering.index("commit") < ordering.index("engram_mirror")

    def test_engram_error_does_not_abort_stream(self):
        """REQ-6 / REQ-10 / SCN-4: Engram failure must NOT raise to caller."""
        from app.core.engram_client import EngramError

        session = MagicMock()

        with patch("app.api.chat.engram_mirror") as fake_mirror:
            fake_mirror.side_effect = EngramError("Engram caído")

            async def run():
                yield "event: sources\ndata: []\n\n"
                self._run_persistence_block(
                    session=session,
                    engram_mirror=fake_mirror,
                    user_msg_content="hola",
                    assistant_content="hi",
                    user_id=1,
                    project_id=1,
                    ordering=[],
                )
                yield "event: done\ndata: null\n\n"

            events = _drain(run())

        assert events[-1].startswith("event: done")
        session.commit.assert_called_once()


class TestPostgresLivenessCheck:
    """F12 (REQ-11 / SCN-5): liveness check returns 503 when Postgres unreachable.

    The route must run a SELECT 1 BEFORE opening the SSE stream. If that probe
    raises SQLAlchemyError, the route returns HTTP 503 (NOT 200 + event: error).
    """

def test_postgres_down_returns_503(self):
    """Liveness probe raises SQLAlchemyError -> route raises HTTPException(503)."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy.exc import SQLAlchemyError

    from app.api.chat import router
    from app.api.dependencies import get_current_user

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: {"user_id": 1, "username": "test"}

    client = TestClient(app)

    # Patch the reference the ROUTE uses (chat module imports SessionLocal
    # by name), not only the source module.
    with patch("app.api.chat.SessionLocal") as mock_session_local:
        # SessionLocal() returns a context manager whose .execute raises.
        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_db.execute.side_effect = SQLAlchemyError("connection refused")
        mock_session_local.return_value = mock_db

        response = client.post(
            "/api/chat",
            json={"project_id": None, "message": "hello"},
        )

        assert response.status_code == 503
        assert "Database unavailable" in response.json()["detail"]


# ---------------------------------------------------------------------------
# F13 (REQ-PMCP-1 / REQ-ATT-1) — event: attachment on the SSE channel
# ---------------------------------------------------------------------------


def _attachment_event(kind="screenshot", mime="image/png", url="/api/chat/attachments/abc?token=xyz",
 storage_path=):
    payload = {
        "kind": kind,
        "mime": mime,
        "url": url,
        "filename": "diagram-12345.png",
        "storage_path": "/app/uploads/screenshots/abc.png",
        "source_url": "data:image/png;base64,xxx",
        "bytes": 1024,
    }
    return f"event: attachment\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def test_chat_stream_emits_attachment_event_between_token_and_done(monkeypatch):
    """REQ-PMCP-1 / SCN-PMCP-1: ``event: attachment`` arrives AFTER the last
    ``event: token`` and BEFORE ``event: done``. The on-wire payload
    strips server-only fields (storage_path, source_url, bytes).
    """
    from app.api import chat as chat_module

    patches = _patch_chat_route(
        run_agent_events=[
            {"event": "token", "data": "Aquí va el diagrama:"},
            {"event": "attachment", "data": {
                "kind": "screenshot",
                "mime": "image/png",
                "url": "/api/chat/attachments/abc-uuid?token=signed.jwt",
                "filename": "diagram-12345.png",
                "storage_path": "/app/uploads/screenshots/abc-uuid.png",
                "source_url": "data:image/png;base64,xxx",
                "bytes": 1024,
            }},
            {"event": "done", "data": None},
        ],
    )
    for p in patches:
        p.start()

    try:
        body = chat_module.ChatRequest(message="diagrama de secuencia")
        current_user = {"user_id": 1, "username": "architect"}

        async def _drive():
            response = await _call_chat(chat_module, body, current_user)
            return await _drive_event_generator(response.body_iterator)

        chunks = asyncio.run(_drive())
        body_text = "".join(chunks)
        assert "event: attachment" in body_text
        # The on-wire payload must contain the URL with the signed token.
        assert "/api/chat/attachments/abc-uuid?token=signed.jwt" in body_text
        # Storage path / source URL / bytes must NOT leak to the wire.
        assert "/app/uploads/" not in body_text
        assert "data:image/png;base64,xxx" not in body_text
        # Attachment event ordering: AFTER token, BEFORE done.
        idx_token = body_text.find(_token("Aquí va el diagrama:"))
        idx_attach = body_text.find("event: attachment")
        idx_done = body_text.find(_done())
        assert 0 <= idx_token < idx_attach < idx_done
    finally:
        for p in patches:
            p.stop()


def test_chat_stream_no_attachment_event_when_no_mermaid(monkeypatch):
    """SCN-PMCP-2: no ``event: attachment`` when run_agent yields no Mermaid block."""
    from app.api import chat as chat_module

    patches = _patch_chat_route(
        run_agent_events=[
            {"event": "token", "data": "Sin diagrama, solo texto."},
            {"event": "done", "data": None},
        ],
    )
    for p in patches:
        p.start()

    try:
        body = chat_module.ChatRequest(message="hola")
        current_user = {"user_id": 1, "username": "architect"}

        async def _drive():
            response = await _call_chat(chat_module, body, current_user)
            return await _drive_event_generator(response.body_iterator)

        chunks = asyncio.run(_drive())
        body_text = "".join(chunks)
        assert "event: attachment" not in body_text
    finally:
        for p in patches:
            p.stop()


def test_chat_stream_attachments_persisted_atomically_in_pre_done_tx(monkeypatch):
    """REQ-ATT-1: when an attachment SSE event arrives, the route persists
    it on the assistant message in the SAME pre-``done`` transaction. We
    assert that ``save_message`` was invoked with an ``attachments=``
    kwarg carrying the collected dict.
    """
    from app.api import chat as chat_module

    captured_attachments: list = []

    patches = _patch_chat_route(
        run_agent_events=[
            {"event": "token", "data": "hola"},
            {"event": "attachment", "data": {
                "kind": "screenshot",
                "mime": "image/png",
                "url": "/api/chat/attachments/x?token=t",
                "filename": "diagram.png",
                "storage_path": "/app/uploads/screenshots/x.png",
                "source_url": None,
                "bytes": 1,
            }},
            {"event": "done", "data": None},
        ],
    )

    real_save_message = chat_module.save_message

    def _capture_save_message(_db, **kw):
        if kw.get("role") == "assistant":
            captured_attachments.extend(kw.get("attachments") or [])
        return real_save_message(_db, **kw)

    patches.append(
        patch.object(
            chat_module, "save_message",
            side_effect=lambda _db, **_kw: _capture_save_message(_db, **_kw),
        )
    )
    for p in patches:
        p.start()

    try:
        body = chat_module.ChatRequest(message="diagrama")
        current_user = {"user_id": 1, "username": "architect"}

        async def _drive():
            response = await _call_chat(chat_module, body, current_user)
            await _drive_event_generator(response.body_iterator)

        asyncio.run(_drive())
    finally:
        for p in patches:
            p.stop()

    assert len(captured_attachments) == 1
    assert captured_attachments[0]["filename"] == "diagram.png"
