"""
Tests for app.core.agent (slice F11.3a).

Covers REQ-3 (build_agent + format_rag_context), REQ-6 (degraded event),
REQ-8 (architect_pattern precedence) and SCN-1 / SCN-2 / SCN-3 streams.

The ``run_agent`` tests mock ``agent.astream_events`` at the agent factory
boundary so they exercise the full yield ordering without spinning a real
LangChain runtime.
"""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# format_rag_context
# ---------------------------------------------------------------------------


def _make_doc(content: str, source_type: str | None = None, **meta):
    doc = MagicMock()
    doc.page_content = content
    doc.metadata = {"source_type": source_type, **meta} if source_type is not None else meta
    return doc


def test_format_rag_context_empty():
    from app.core.agent import format_rag_context

    assert format_rag_context([]) == "(sin contexto RAG)"


def test_format_rag_context_numbers_documents():
    from app.core.agent import format_rag_context

    docs = [
        _make_doc("pattern body", source_type="architect_pattern", pattern_name="Saga"),
        _make_doc("chunk body", source_type="document_chunk", filename="a.pdf"),
    ]
    block = format_rag_context(docs)
    assert block.startswith("[1] Saga")
    assert "pattern body" in block
    assert "[2] a.pdf" in block
    assert "chunk body" in block


def test_format_rag_context_caps_at_five():
    """REQ-8: cap to k≤5 to keep prompt within budget."""
    from app.core.agent import format_rag_context, _RAG_DOCS_CAP

    docs = [_make_doc(f"d{i}") for i in range(_RAG_DOCS_CAP + 3)]
    block = format_rag_context(docs)
    # Only the first 5 should appear numbered.
    for index in range(1, _RAG_DOCS_CAP + 1):
        assert f"[{index}]" in block
    assert f"[{_RAG_DOCS_CAP + 1}]" not in block


def test_has_architect_pattern_helper():
    from app.core.agent import _has_architect_pattern

    assert _has_architect_pattern([]) is False
    assert _has_architect_pattern([_make_doc("x")]) is False
    assert (
        _has_architect_pattern(
            [_make_doc("x", source_type="architect_pattern", pattern_name="Saga")]
        )
        is True
    )


def test_build_system_prompt_composes_sections():
    from app.core.agent import _build_system_prompt, ARCHITECT_PERSONA, LIBRARY_HINT

    docs = [_make_doc("body", source_type="architect_pattern", pattern_name="Saga")]
    prompt = _build_system_prompt(docs)
    assert ARCHITECT_PERSONA in prompt
    assert LIBRARY_HINT in prompt
    assert "Saga" in prompt
    assert "body" in prompt


# ---------------------------------------------------------------------------
# build_agent
# ---------------------------------------------------------------------------


def test_build_agent_accepts_empty_tools():
    """REQ-3: agent must build without tools (RAG-only mode)."""
    from app.core import agent

    captured: dict = {}

    def _fake_create_agent(model, tools, system_prompt):
        captured["model"] = model
        captured["tools"] = tools
        captured["system_prompt"] = system_prompt
        return MagicMock(name="compiled-agent")

    with patch.object(agent, "_create_agent", side_effect=_fake_create_agent):
        agent.build_agent(model="fake-model", system_prompt="fake-prompt", tools=None)

    assert captured["tools"] == []
    assert captured["system_prompt"] == "fake-prompt"


def test_build_agent_passes_tools_through():
    """REQ-3: tool list reaches the agent factory unchanged."""
    from app.core import agent

    fake_tools = [MagicMock(name="t1"), MagicMock(name="t2")]
    captured: dict = {}

    def _fake_create_agent(model, tools, system_prompt):
        captured["tools"] = tools
        return MagicMock(name="compiled-agent")

    with patch.object(agent, "_create_agent", side_effect=_fake_create_agent):
        agent.build_agent(model="m", system_prompt="s", tools=fake_tools)

    assert captured["tools"] == fake_tools


# ---------------------------------------------------------------------------
# run_agent — degraded path (SCN-3)
# ---------------------------------------------------------------------------


def test_run_agent_emits_degraded_when_context7_fails():
    """SCN-3: Context7 unavailable → one degraded event then continue."""
    from app.core import agent
    from app.core.context7_mcp import Context7Unavailable

    fake_agent = MagicMock()

    async def _empty_astream(*_a, **_kw):
        if False:  # pragma: no cover - never iterates
            yield {}

    fake_agent.astream_events = _empty_astream

    with patch.object(agent, "build_agent", return_value=fake_agent), \
         patch.object(agent, "_try_get_context7_tools", AsyncMock(
             return_value=([], {"source": "context7",
                                "reason": "context7_timeout",
                                "fallback": "rag_only",
                                "message": "boom"})
         )):
        async def _drive():
            events = []
            async for ev in agent.run_agent(
                model="m",
                message="hello",
                callbacks=[],
                rag_documents=[],
            ):
                events.append(ev)
                if len(events) > 10:
                    break
            return events

        events = asyncio.run(_drive())

    # First event must be the degraded event; done must be the last.
    assert events[0]["event"] == "degraded"
    assert events[0]["data"]["reason"] == "context7_timeout"
    assert events[-1]["event"] == "done"


def test_run_agent_no_degraded_when_context7_ok():
    """When Context7 returns tools, no degraded event is emitted."""
    from app.core import agent

    fake_agent = MagicMock()

    async def _empty_astream(*_a, **_kw):
        if False:  # pragma: no cover
            yield {}

    fake_agent.astream_events = _empty_astream

    with patch.object(agent, "build_agent", return_value=fake_agent), \
         patch.object(agent, "_try_get_context7_tools", AsyncMock(
             return_value=([MagicMock(name="resolve-library-id"), MagicMock(name="query-docs")], None),
         )), \
         patch.object(agent, "_try_get_puppeteer_tools", AsyncMock(
             return_value=([], None),
         )):
        async def _drive():
            events = []
            async for ev in agent.run_agent(
                model="m",
                message="hi",
                callbacks=[],
                rag_documents=[],
            ):
                events.append(ev)
                if len(events) > 10:
                    break
            return events

        events = asyncio.run(_drive())

    assert all(ev["event"] != "degraded" for ev in events)
    assert events[-1]["event"] == "done"


# ---------------------------------------------------------------------------
# run_agent — REQ-8 precedence (architect_pattern → no Context7)
# ---------------------------------------------------------------------------


def test_run_agent_skips_context7_when_architect_pattern_present():
    """REQ-8: when RAG covers an architect_pattern, Context7 fetch is skipped."""
    from app.core import agent

    fake_agent = MagicMock()

    async def _empty_astream(*_a, **_kw):
        if False:  # pragma: no cover
            yield {}

    fake_agent.astream_events = _empty_astream

    captured_tools: dict = {}

    def _capture_build(model, system_prompt, tools=None):
        captured_tools["tools"] = list(tools or [])
        return fake_agent

    docs = [
        _make_doc("saga body", source_type="architect_pattern", pattern_name="Saga")
    ]

    with patch.object(agent, "build_agent", side_effect=_capture_build), \
         patch.object(agent, "_try_get_context7_tools", AsyncMock()) as c7, \
         patch.object(agent, "_try_get_puppeteer_tools", AsyncMock(return_value=([], None))):

        async def _drive():
            events = []
            async for ev in agent.run_agent(
                model="m",
                message="explica saga",
                callbacks=[],
                rag_documents=docs,
            ):
                events.append(ev)
                if len(events) > 10:
                    break
            return events

        asyncio.run(_drive())

    # Context7 fetch must NOT have been called.
    c7.assert_not_called()
    # Agent must have been built with empty tools (puppeteer mocked to empty too).
    assert captured_tools["tools"] == []


# ---------------------------------------------------------------------------
# run_agent — token + tool streaming (SCN-1)
# ---------------------------------------------------------------------------


def _aiter_from_list(events):
    async def _gen():
        for ev in events:
            yield ev
    return _gen()


def test_run_agent_streams_tokens_then_done():
    """SCN-2: with empty tools the stream yields only tokens then done."""
    from app.core import agent

    fake_agent = MagicMock()

    # Mocked astream_events yields a sequence of chat-model stream chunks.
    def _make_chunk(text: str):
        chunk = MagicMock()
        chunk.content = text
        return chunk

    raw_events = [
        {"event": "on_chat_model_stream", "name": "M", "data": {"chunk": _make_chunk("Ho")}},
        {"event": "on_chat_model_stream", "name": "M", "data": {"chunk": _make_chunk("la")}},
        {"event": "on_chat_model_end", "name": "M", "data": {}},
    ]

    fake_agent.astream_events = lambda *a, **kw: _aiter_from_list(raw_events)

    with patch.object(agent, "build_agent", return_value=fake_agent), \
         patch.object(agent, "_try_get_context7_tools", AsyncMock(return_value=([], None))), \
         patch.object(agent, "_try_get_puppeteer_tools", AsyncMock(return_value=([], None))):

        async def _drive():
            events = []
            async for ev in agent.run_agent(
                model="m",
                message="hi",
                callbacks=[],
                rag_documents=[],
            ):
                events.append(ev)
            return events

        events = asyncio.run(_drive())

    # First events should be tokens; final event should be done; no tool events.
    types = [ev["event"] for ev in events]
    assert "tool_start" not in types
    assert "tool_end" not in types
    assert "degraded" not in types
    assert types[-1] == "done"
    # Concatenated token payloads reproduce the model output.
    tokens = [ev["data"] for ev in events if ev["event"] == "token"]
    assert "".join(tokens) == "Hola"


def test_run_agent_emits_tool_start_and_end_around_tokens():
    """SCN-1: tool_start → tool_end → token* → done."""
    from app.core import agent

    fake_agent = MagicMock()

    def _make_chunk(text: str):
        chunk = MagicMock()
        chunk.content = text
        return chunk

    raw_events = [
        {"event": "on_tool_start", "name": "resolve-library-id",
         "data": {"input": {"libraryName": "requests"}}},
        {"event": "on_tool_end", "name": "resolve-library-id",
         "data": {"output": "/python/requests"}},
        {"event": "on_chat_model_stream", "name": "M",
         "data": {"chunk": _make_chunk("OK")}},
        {"event": "on_chat_model_end", "name": "M", "data": {}},
    ]

    fake_agent.astream_events = lambda *a, **kw: _aiter_from_list(raw_events)

    with patch.object(agent, "build_agent", return_value=fake_agent), \
         patch.object(agent, "_try_get_context7_tools",
                      AsyncMock(return_value=([MagicMock(name="t1")], None))), \
         patch.object(agent, "_try_get_puppeteer_tools", AsyncMock(return_value=([], None))):

        async def _drive():
            events = []
            async for ev in agent.run_agent(
                model="m",
                message="hi",
                callbacks=[],
                rag_documents=[],
            ):
                events.append(ev)
            return events

        events = asyncio.run(_drive())

    types = [ev["event"] for ev in events]
    assert types[0] == "tool_start"
    assert types[1] == "tool_end"
    assert types[-1] == "done"
    assert types.count("token") >= 1
    tool_end_payload = events[1]["data"]
    assert tool_end_payload["tool"] == "resolve-library-id"
    assert tool_end_payload["result_length"] == len(b"/python/requests")
    assert tool_end_payload["status"] == "ok"


def test_run_agent_truncates_oversized_tool_result():
    """REQ-9 / ADR-010: cap tool result text at 4000 chars with marker."""
    from app.core.agent import _truncate_tool_result

    huge = "x" * 5000
    text, length = _truncate_tool_result(huge)
    assert len(text) <= 4000
    assert "[truncado" in text
    # Length is the on-wire byte length, not the source.
    assert length == len(text.encode("utf-8"))


def test_run_agent_token_emission_preserves_nonempty_strings_only():
    """Empty / list-without-text chunks must NOT become empty SSE tokens."""
    from app.core.agent import _extract_token_text

    chunk = MagicMock()
    chunk.content = ""
    assert _extract_token_text(chunk) is None

    chunk2 = MagicMock()
    chunk2.content = []
    assert _extract_token_text(chunk2) is None

    chunk3 = MagicMock()
    chunk3.content = [{"type": "text", "text": "hello"}, {"type": "tool_use"}]
    assert _extract_token_text(chunk3) == "hello"


def test_run_agent_yields_error_when_astream_raises():
    """If ``agent.astream_events`` itself raises, surface as ``error`` event."""
    from app.core import agent

    fake_agent = MagicMock()

    def _boom(*_a, **_kw):
        raise RuntimeError("simulated astream failure")

    fake_agent.astream_events = _boom

    with patch.object(agent, "build_agent", return_value=fake_agent), \
         patch.object(agent, "_try_get_context7_tools",
                      AsyncMock(return_value=([], None))), \
         patch.object(agent, "_try_get_puppeteer_tools", AsyncMock(return_value=([], None))):

        async def _drive():
            events = []
            async for ev in agent.run_agent(
                model="m",
                message="hi",
                callbacks=[],
                rag_documents=[],
            ):
                events.append(ev)
            return events

        events = asyncio.run(_drive())

    types = [ev["event"] for ev in events]
    assert types[0] == "error"
    assert "simulated astream failure" in events[0]["data"]


# ---------------------------------------------------------------------------
# Tool fetch wrapping
# ---------------------------------------------------------------------------


def test_try_get_context7_tools_returns_tools_list_on_success():
    from app.core import agent

    async def _drive():
        return await agent._try_get_context7_tools()

    # Patch the inner get_context7_tools the helper imports.
    fake_tools = [MagicMock(name="t1")]

    async def _fake_get():
        return fake_tools

    with patch.dict("sys.modules", {"app.core.context7_mcp": MagicMock(
        get_context7_tools=_fake_get,
    )}):
        # Force re-import inside the helper.
        import importlib
        import app.core.context7_mcp as ctx7_mod
        with patch.object(ctx7_mod, "get_context7_tools", _fake_get):
            tools, degraded = asyncio.run(_drive())

    assert tools == fake_tools
    assert degraded is None


def test_try_get_context7_tools_emits_typed_degraded_on_failure():
    from app.core import agent
    from app.core.context7_mcp import Context7Unavailable

    async def _drive():
        return await agent._try_get_context7_tools()

    with patch("app.core.context7_mcp.get_context7_tools",
               AsyncMock(side_effect=Context7Unavailable("boom", reason="context7_rate_limited"))):
        tools, degraded = asyncio.run(_drive())

    assert tools == []
    assert degraded["reason"] == "context7_rate_limited"
    assert degraded["fallback"] == "rag_only"


# ---------------------------------------------------------------------------
# Task 5.2 — Langfuse metadata wiring in run_agent
# ---------------------------------------------------------------------------


def test_run_agent_threads_metadata_into_astream_config():
    """REQ-5 / SCN-7: ``user_id`` / ``project_id`` / model land in config."""
    from app.core import agent

    fake_agent = MagicMock()

    async def _empty_astream(*_a, **_kw):
        if False:  # pragma: no cover
            yield {}

    fake_agent.astream_events = _empty_astream

    captured: dict = {}

    def _capture_astream(input, config=None, **kwargs):
        captured["config"] = config
        captured["input"] = input
        return _empty_astream()

    fake_agent.astream_events = _capture_astream

    fake_model = MagicMock()
    fake_model.model_name = "gpt-test-model"

    with patch.object(agent, "build_agent", return_value=fake_agent), \
         patch.object(agent, "_try_get_context7_tools",
                      AsyncMock(return_value=([], None))):

        async def _drive():
            async for _ in agent.run_agent(
                model=fake_model,
                message="hi",
                callbacks=[MagicMock()],
                rag_documents=[],
                user_id=42,
                project_id=13,
            ):
                pass

        asyncio.run(_drive())

    config = captured["config"]
    assert "callbacks" in config
    assert config["metadata"]["user_id"] == 42
    assert config["metadata"]["project_id"] == "13"
    assert config["metadata"]["model"] == "gpt-test-model"
    assert config["run_name"] == "chat/user-42/project-13"


def test_run_agent_records_none_project_as_string_none():
    """REQ-5: project_id=None is recorded as the string 'none' for filterability."""
    from app.core import agent

    fake_agent = MagicMock()
    captured: dict = {}

    def _capture_astream(input, config=None, **kwargs):
        captured["config"] = config

        async def _gen():
            if False:  # pragma: no cover
                yield {}

        return _gen()

    fake_agent.astream_events = _capture_astream

    with patch.object(agent, "build_agent", return_value=fake_agent), \
         patch.object(agent, "_try_get_context7_tools",
                      AsyncMock(return_value=([], None))):

        async def _drive():
            async for _ in agent.run_agent(
                model=MagicMock(model_name="m"),
                message="hi",
                callbacks=[],
                rag_documents=[],
                user_id=1,
                project_id=None,
            ):
                pass

        asyncio.run(_drive())

    assert captured["config"]["metadata"]["project_id"] == "none"
    assert captured["config"]["run_name"] == "chat/user-1/project-none"
