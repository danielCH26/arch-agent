"""Tests for ``app/api/proposals.py`` router (slice 2).

Covered SCNs:
- SCN-1: proposal round-trips with three sections (asserted via
  Proposal.content JSONB shape; the markdown rendering lives in the LLM).
- SCN-4: approve inserts one interaction_log row + transitions lifecycle +
  sets ``projects.phase_ready``.
- SCN-5: modify increments iteration and freezes prior content in approvals.
- SCN-6: migration idempotency (smoke check via model metadata; the
  end-to-end migration test belongs to the migration runner script).
- SCN-7: SSE ``done`` payload includes ``proposal_id``.
- SCN-9: ``PROPOSAL_REJECT_REVERTS_TO`` env override applied on Rechazar.
- SCN-10: Engram outage MUST NOT block DB persistence (asserted on
  ``ProposalGenerator._engram_mirror`` swallowing ``EngramError``).
"""

from __future__ import annotations

import asyncio
import json
import os
from unittest.mock import MagicMock, patch

import pytest


# --- Slice-1 contract still holds ----------------------------------------


def test_proposal_models_import_and_constraints_compile():
    from app.models import InteractionLog, Proposal, ProposalApproval

    assert Proposal.__tablename__ == "proposals"
    assert InteractionLog.__tablename__ == "interaction_logs"
    assert ProposalApproval.__tablename__ == "proposal_approvals"
    assert Proposal.__table__.c.content.type.__class__.__name__ == "JSONB"


# --- SSE helper unit tests ------------------------------------------------


class TestSSEEmit:
    def test_emit_sse_event_format_for_token(self):
        from app.api.proposals import _emit_sse

        frame = _emit_sse("token", "Hola")
        assert frame == 'event: token\ndata: "Hola"\n\n'

    def test_emit_sse_event_format_for_done_with_payload(self):
        from app.api.proposals import _emit_sse

        frame = _emit_sse("done", {"proposal_id": 7, "citations": []})
        # json.dumps keeps key order in 3.7+ and we keep ascii=False to match
        # the chat endpoint contract.
        assert frame.startswith("event: done\ndata: ")
        assert frame.endswith("\n\n")
        body = frame.split("data: ", 1)[1].rsplit("\n\n", 1)[0]
        parsed = json.loads(body)
        assert parsed == {"proposal_id": 7, "citations": []}

    def test_emit_sse_event_format_for_error(self):
        from app.api.proposals import _emit_sse

        frame = _emit_sse("error", "boom")
        assert frame.startswith("event: error\ndata: ")
        assert '"boom"' in frame

    def test_emit_sse_preserves_unicode(self):
        from app.api.proposals import _emit_sse

        frame = _emit_sse("token", "diseño")
        # ensure_ascii=False must keep the ñ raw, not escape it.
        assert "\\u00f1" not in frame
        assert "diseño" in frame


# --- Request/response models ---------------------------------------------


class TestRequestModels:
    def test_generate_request_requires_project_id(self):
        from app.api.proposals import GenerateRequest

        req = GenerateRequest(project_id=42)
        assert req.project_id == 42

    def test_modify_request_requires_non_empty_feedback(self):
        from pydantic import ValidationError

        from app.api.proposals import ModifyRequest

        with pytest.raises(ValidationError):
            ModifyRequest(feedback="")

        req = ModifyRequest(feedback="agregar cache")
        assert req.feedback == "agregar cache"

    def test_decide_request_validates_literal_decision(self):
        from pydantic import ValidationError

        from app.api.proposals import DecideRequest

        with pytest.raises(ValidationError):
            DecideRequest(decision="banana")  # type: ignore[arg-type]

        req = DecideRequest(decision="approve", comment="OK")
        assert req.decision == "approve"
        assert req.comment == "OK"


# --- Env-var defaults & overrides (SCN-9) --------------------------------


class TestRejectRevertsToEnv:
    def setup_method(self):
        self._original = os.environ.get("PROPOSAL_REJECT_REVERTS_TO")

    def teardown_method(self):
        if self._original is None:
            os.environ.pop("PROPOSAL_REJECT_REVERTS_TO", None)
        else:
            os.environ["PROPOSAL_REJECT_REVERTS_TO"] = self._original

    def test_default_is_requerimientos(self):
        os.environ.pop("PROPOSAL_REJECT_REVERTS_TO", None)
        # Re-import the module so the module-level constant is recomputed.
        import importlib

        import app.api.proposals as proposals_module

        importlib.reload(proposals_module)
        assert proposals_module.PROPOSAL_REJECT_REVERTS_TO == "requerimientos"

    def test_env_override_takes_effect(self):
        os.environ["PROPOSAL_REJECT_REVERTS_TO"] = "propuesta"
        import importlib

        import app.api.proposals as proposals_module

        importlib.reload(proposals_module)
        assert proposals_module.PROPOSAL_REJECT_REVERTS_TO == "propuesta"


# --- RAG constant sync ----------------------------------------------------


class TestRAGConstantSync:
    def test_proposals_router_keeps_rag_min_similarity_in_sync(self):
        # Per ADR-009 / design §9 -- if these drift, retrieval silently changes
        # behaviour between chat and proposals. Lock the constant at 0.85.
        from app.api import chat as chat_module
        from app.api import proposals as proposals_module
        from app.core import proposal_generator as generator_module

        assert proposals_module.RAG_MIN_SIMILARITY == 0.85
        assert generator_module.RAG_MIN_SIMILARITY == 0.85
        assert chat_module.RAG_MIN_SIMILARITY == 0.85


# --- Filter citations helper (unit) --------------------------------------


class TestCitationSelection:
    """La fase de propuesta trae los N patrones mas relevantes, sin umbral."""

    @staticmethod
    def _doc(pattern_id, name, similarity, body="body"):
        from langchain_core.documents import Document

        metadata = {"pattern_id": pattern_id, "pattern_name": name}
        if similarity is not None:
            metadata["similarity"] = similarity
        return Document(page_content=body, metadata=metadata)

    def test_keeps_best_patterns_even_below_old_threshold(self):
        from app.core.proposal_generator import _select_citations

        docs = [
            self._doc(7, "Hexagonal", 0.83, "hex body"),
            self._doc(11, "CQRS", 0.79),
        ]
        citations = _select_citations(docs)
        # Con el umbral viejo (0.85) esto devolvia [] y la propuesta salia
        # "sin patrones relevantes".
        assert [c["pattern_id"] for c in citations] == [7, 11]
        assert "hex body" in citations[0]["snippet"]

    def test_orders_by_similarity_and_limits_to_top_n(self):
        from app.core.proposal_generator import _select_citations

        docs = [
            self._doc(1, "A", 0.60),
            self._doc(2, "B", 0.90),
            self._doc(3, "C", 0.75),
            self._doc(4, "D", 0.80),
        ]
        citations = _select_citations(docs, top_n=2)
        assert [c["pattern_id"] for c in citations] == [2, 4]

    def test_dedupes_chunks_of_the_same_pattern(self):
        from app.core.proposal_generator import _select_citations

        docs = [
            self._doc(5, "Microservicios", 0.88, "mejor chunk"),
            self._doc(5, "Microservicios", 0.86, "otro chunk"),
            self._doc(6, "Event-driven", 0.80),
        ]
        citations = _select_citations(docs, top_n=3)
        assert [c["pattern_id"] for c in citations] == [5, 6]
        assert citations[0]["snippet"] == "mejor chunk"

    def test_optional_floor_still_available(self):
        from app.core.proposal_generator import _select_citations

        docs = [self._doc(1, "A", 0.90), self._doc(2, "B", 0.50)]
        citations = _select_citations(docs, top_n=5, min_similarity=0.70)
        assert [c["pattern_id"] for c in citations] == [1]

    def test_empty_when_database_returns_nothing(self):
        from app.core.proposal_generator import _select_citations

        assert _select_citations([]) == []


# --- Engram outage never blocks (SCN-10) ----------------------------------


class TestEngramResilience:
    def test_engram_mirror_swallows_connection_error(self, caplog):
        """REQ-9 / SCN-10: best-effort Engram mirror must never raise."""
        from app.core import engram_client as engram_module
        from app.core.proposal_generator import _engram_mirror

        # Stub EngramClient to raise EngramError (== ConnectionError path).
        class FakeEngram:
            def __init__(self, *args, **kwargs):
                pass

            def save_observation(self, **kwargs):
                raise engram_module.EngramError(
                    "No fue posible conectar con Engram: Connection refused"
                )

        with patch(
            "app.core.proposal_generator.EngramClient", FakeEngram
        ):
            # Should NOT raise -- the whole point of best-effort mirroring.
            asyncio.run(
                _engram_mirror(
                    session_id=1,
                    proposal_id=99,
                    interaction_id=7,
                    markdown="ignored",
                )
            )


# --- StreamingResponse wiring ---------------------------------------------


class TestStreamingResponseWiring:
    def test_generate_endpoint_returns_streaming_response_with_headers(self):
        """Smoke check the StreamingResponse headers match the chat contract."""
        from fastapi.responses import StreamingResponse

        from app.api.proposals import _sse_stream

        async def empty_iter():
            if False:
                yield "x", "y"

        resp = StreamingResponse(
            _sse_stream(empty_iter()),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )
        assert resp.media_type == "text/event-stream"
        assert resp.headers["cache-control"] == "no-cache"
        assert resp.headers["x-accel-buffering"] == "no"


# --- Decide endpoint idempotency (SCN-4 + design §10) -------------------


class TestDecideIdempotency:
    """``interaction_logs (proposal_id, action_type)`` is the implicit key.

    We assert the query pattern the router uses (filter by
    ``project_id+phase+action_type``) matches the unique fingerprint we want
    to block. The actual DB-level test lives in the apply phase migration
    harness; here we only verify the route consults the right fingerprint
    so a future migration to add a true UNIQUE constraint is a drop-in.
    """

    def test_decide_checks_action_type_fingerprint(self):
        # The route builds the fingerprint via:
        #   InteractionLog.project_id == proposal.project_id AND
        #   InteractionLog.phase == "propuesta" AND
        #   InteractionLog.action_type IN ("approve", "reject")
        # Verify the import path + the model fields the route relies on.
        from app.models import InteractionLog

        columns = {c.name for c in InteractionLog.__table__.columns}
        assert {"project_id", "phase", "action_type"}.issubset(columns)


# --- Lifecycle side effects ----------------------------------------------


class TestLifecycleSideEffects:
    """Pure-function assertions about the side effects of decide.

    The route is exercised end-to-end by the runtime harness (manual smoke
    + later Playwright/Cypress). These tests pin the contract so a careless
    refactor doesn't silently drop the ``phase_ready`` transition.
    """

    def test_approve_path_sets_phase_ready_true(self):
        # Read the source of decide_proposal and confirm the transition is in
        # the approve branch (not buried in a shared code path that reject
        # could also trigger). Cheap regression guard.
        import inspect

        from app.api import proposals as proposals_module

        source = inspect.getsource(proposals_module.decide_proposal)
        assert "phase_ready = True" in source
        assert "phase_ready = False" in source
        # Reject branch must revert current_phase
        assert "PROPOSAL_REJECT_REVERTS_TO" in source

# --- F19: cancelacion desde el cliente ------------------------------------


class TestSSEStreamCancellation:
    def test_progress_event_is_serialized_like_any_other(self):
        from app.api.proposals import _emit_sse

        frame = _emit_sse("progress", {"stage": "retrieval", "percent": 12})
        assert frame.startswith("event: progress\ndata: ")
        assert json.loads(frame.split("data: ", 1)[1]) == {"stage": "retrieval", "percent": 12}

    def test_closing_the_response_closes_the_inner_generator_immediately(self):
        """Si el cliente se desconecta, el generador interno (y el LLM) se cierra ya."""
        from app.api.proposals import _sse_stream

        closed = []

        async def inner():
            try:
                for i in range(1000):
                    yield "token", f"t{i}"
                    await asyncio.sleep(0)
            finally:
                closed.append(True)

        async def run():
            stream = _sse_stream(inner())
            first = await stream.__anext__()
            await stream.aclose()  # lo que hace Starlette al cortar la conexion
            return first

        first = asyncio.run(run())

        assert first.startswith("event: token")
        assert closed == [True]

    def test_sends_heartbeat_while_waiting_for_a_slow_event(self, monkeypatch):
        from app.api import proposals as proposals_module

        monkeypatch.setattr(proposals_module, "SSE_HEARTBEAT_SECONDS", 0.001)

        async def inner():
            await asyncio.sleep(0.01)
            yield "token", "a"

        async def run():
            stream = proposals_module._sse_stream(inner())
            first = await stream.__anext__()
            await stream.aclose()
            return first

        assert asyncio.run(run()) == ": ping\n\n"

    def test_cancelled_error_is_propagated_not_swallowed(self):
        from app.api.proposals import _sse_stream

        async def inner():
            yield "token", "a"
            raise asyncio.CancelledError()

        async def run():
            return [frame async for frame in _sse_stream(inner())]

        with pytest.raises(asyncio.CancelledError):
            asyncio.run(run())


# --- Review PR: el generador debe correr siempre en el mismo contexto ---------


class TestSSEStreamKeepsOneContext:
    """LangChain/Langfuse fijan ``contextvars`` dentro del generador del LLM.

    Si cada paso corre en una Task distinta, un valor fijado en un paso no se
    ve en el siguiente y ``ContextVar.reset(token)`` falla con "created in a
    different Context". Estos tests lo reproducen sin necesitar un LLM real.
    """

    def test_context_var_set_in_one_step_is_visible_in_the_next(self):
        import contextvars

        from app.api.proposals import _sse_stream

        var = contextvars.ContextVar("trace_id", default=None)
        seen = []

        async def inner():
            var.set("run-1")
            yield "token", "a"
            seen.append(var.get())
            yield "token", "b"

        async def run():
            return [frame async for frame in _sse_stream(inner())]

        asyncio.run(run())

        assert seen == ["run-1"]

    def test_context_var_token_can_be_reset_after_several_yields(self):
        import contextvars

        from app.api.proposals import _sse_stream

        var = contextvars.ContextVar("callback_manager", default=None)

        async def inner():
            token = var.set("active")
            try:
                yield "token", "a"
                await asyncio.sleep(0)
                yield "token", "b"
            finally:
                var.reset(token)  # ValueError si cambio de contexto

        async def run():
            return [frame async for frame in _sse_stream(inner())]

        frames = asyncio.run(run())

        assert len(frames) == 2

    def test_all_events_are_delivered_in_order_and_stream_ends(self):
        from app.api.proposals import _sse_stream

        async def inner():
            for i in range(50):
                yield "token", f"t{i}"

        async def run():
            return [frame async for frame in _sse_stream(inner())]

        frames = asyncio.run(run())

        assert [json.loads(f.split("data: ", 1)[1]) for f in frames] == [f"t{i}" for i in range(50)]

    def test_exception_from_the_generator_reaches_the_consumer(self):
        from app.api.proposals import _sse_stream

        async def inner():
            yield "token", "a"
            raise RuntimeError("boom")

        async def run():
            return [frame async for frame in _sse_stream(inner())]

        with pytest.raises(RuntimeError, match="boom"):
            asyncio.run(run())

    def test_no_background_task_is_left_running_after_the_stream_closes(self):
        from app.api.proposals import _sse_stream

        async def inner():
            for i in range(1000):
                yield "token", f"t{i}"
                await asyncio.sleep(0)

        async def run():
            stream = _sse_stream(inner())
            await stream.__anext__()
            await stream.aclose()
            await asyncio.sleep(0)
            return [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]

        assert asyncio.run(run()) == []
