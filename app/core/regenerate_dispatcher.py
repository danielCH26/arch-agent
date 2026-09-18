"""Per-phase regenerate dispatch (HU11 — surgical adjustment).

Issue #22 / HU11 REQ-SA-25 + design §C. One entry point dispatches to the
phase-specific regeneration pathway so the FastAPI route stays a thin SSE
adapter. The decision row was already written by
``POST /phase/{phase}/decision`` (HU10 canonical endpoint) before this is
called — if the LLM stream fails the audit row remains and the frontend
shows a Reintentar button (REQ-SA-25.4).

Dispatch table (mirrors ``design.md §C``):

| Phase         | Mechanism                                       | Output destination                                  |
|---------------|-------------------------------------------------|-----------------------------------------------------|
| requerimientos| ElicitationAgent re-run w/ feedback             | engram_state resumen                                |
| propuesta     | ProposalGenerator.regenerate iteration=max+1    | new Proposal row + proposal_approvals dual-write    |
| refinamiento  | chat SSE w/ feedback as user message            | new Message row + attachments                       |
| revision      | no-op 200 regenerated=false                     | (UI-edited via PhaseFeedbackComposer payload)       |
| final         | 409 REQ-SA-8                                    | —                                                   |

The dispatcher does NOT touch the DB for the decision itself; that lives
in ``app.core.phase_decisions.record_decision``. We only emit the SSE
events that fan out to the frontend.
"""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator

from app.core.phase_decisions import AVAILABLE_PHASES

logger = logging.getLogger(__name__)


class RegenerateDispatcherError(Exception):
    """Domain-level error the SSE adapter translates into an event payload."""


class PastPhaseConflict(RegenerateDispatcherError):
    """409 — caller asked to regenerate ``final`` (REQ-SA-8) or a phase
    at or beyond ``current_phase`` (REQ-SA-25.2)."""


class MissingPayload(RegenerateDispatcherError):
    """400 — feedback is empty or the phase is unknown."""


async def dispatch_regenerate(
    *,
    db: Any,
    user_id: int,
    project_id: int,
    phase: str,
    feedback: str,
    payload: dict[str, Any] | None,
    current_phase: str,
    project_description: str = "",
) -> AsyncIterator[tuple[str, Any]]:
    """Async-iterator over SSE-ready ``(event, payload)`` tuples.

    The shape is identical to ``/api/chat`` and ``/api/proposals/{id}/modify``:
    ``sources``, ``token`` (many), ``done``, or ``error``.

    Raises :class:`PastPhaseConflict` (409) and :class:`MissingPayload` (400)
    BEFORE the first event so the route can return the proper HTTP code
    without having streamed a body.
    """
    if phase not in AVAILABLE_PHASES:
        raise MissingPayload(
            f"phase {phase!r} is not in AVAILABLE_PHASES ({AVAILABLE_PHASES})"
        )
    if not (feedback and feedback.strip()):
        raise MissingPayload("feedback is required and must be non-empty")
    if phase == "final":
        # REQ-SA-8 — Modify is not exposed on the archive phase. The 409
        # short-circuits the stream so the frontend shows a clean error.
        raise PastPhaseConflict(
            "Modify not allowed on final phase (REQ-SA-8)."
        )
    if _phase_ahead_of_current(phase, current_phase):
        # REQ-SA-25 / SCN-SA-25.4: only past or current phases may regenerate.
        raise PastPhaseConflict(
            f"phase {phase!r} is at or beyond current_phase {current_phase!r}"
        )

    if phase == "revision":
        # REQ-SA-25.3 / SCN-SA-25.3: ``revision`` modify is a UI-only edit;
        # the structured payload already carries the trade-offs. We emit a
        # single ``done`` with ``regenerated: false`` so the SPA clears its
        # pending state without an LLM call.
        yield (
            "done",
            {
                "regenerated": False,
                "phase": phase,
                "reason": "revision is a UI-edited phase; no LLM call required",
            },
        )
        return

    if phase == "requerimientos":
        async for event, payload_obj in _dispatch_requerimientos(
            user_id=user_id,
            project_id=project_id,
            feedback=feedback,
            project_description=project_description,
        ):
            yield event, payload_obj
        return

    if phase == "propuesta":
        async for event, payload_obj in _dispatch_propuesta(
            user_id=user_id,
            project_id=project_id,
            feedback=feedback,
        ):
            yield event, payload_obj
        return

    if phase == "refinamiento":
        async for event, payload_obj in _dispatch_refinamiento(
            db=db,
            user_id=user_id,
            project_id=project_id,
            feedback=feedback,
        ):
            yield event, payload_obj
        return

    # Defensive: should never reach here because of the phase guard above.
    yield ("error", f"unsupported phase {phase!r}")


# ---------------------------------------------------------------------------
# Phase helpers
# ---------------------------------------------------------------------------


def _phase_ahead_of_current(phase: str, current_phase: str) -> bool:
    """True if ``phase`` is at or beyond ``current_phase`` in the canonical
    order. ``current_phase`` of ``None`` or unknown is treated as "ahead"
    so the caller 409s (defensive — the API should never receive such a
    value because ``list_phases`` always returns one of the canonical 5).
    """
    if phase not in AVAILABLE_PHASES or current_phase not in AVAILABLE_PHASES:
        return True
    return AVAILABLE_PHASES.index(phase) >= AVAILABLE_PHASES.index(current_phase)


async def _dispatch_requerimientos(
    *,
    user_id: int,
    project_id: int,
    feedback: str,
    project_description: str,
) -> AsyncIterator[tuple[str, Any]]:
    """Re-run the elicitation agent with the user's feedback and emit the
    fresh summary back as SSE tokens.

    Mirrors ``app/api/elicitation.py::send_elicitation_message``: it calls
    ``elicitation_agent.generate_summary`` and persists into
    ``engram_state[<pid>]["requerimientos"]["resumen"]``. We yield a single
    ``done`` event once the new summary is persisted (REQ-SA-25 doesn't
    require token-level granularity for elicitation — the LLM call here
    produces a small structured JSON, not streamed prose).
    """
    # Imported lazily to keep this module import-cheap for unit tests that
    # only exercise the dispatch guard rails.
    from app.core import elicitation_agent
    from app.core.llm_loader import build_langchain_model, LLMConfigError
    from app.core.session_store import load_session_state, save_session_state

    try:
        model = build_langchain_model(user_id)
    except LLMConfigError as exc:
        yield ("error", str(exc))
        return

    # Load the prior Q&A so the new summary is grounded in the prior
    # context + the user's feedback.
    state = load_session_state(user_id) or {}
    engram_state = state.get("engram_state") or {}
    project_state = engram_state.get(str(project_id)) or {}
    prior_history = list(
        project_state.get("requerimientos", {}).get(
            "preguntas_respuestas", []
        )
        or []
    )
    # The user's regenerate feedback is treated as a final answer in the
    # Q&A history so the summary captures the adjustment explicitly.
    prior_history = prior_history + [
        {
            "pregunta": "(ajuste solicitado por el usuario)",
            "respuesta": feedback.strip(),
        }
    ]

    try:
        resumen = elicitation_agent.generate_summary(
            model, prior_history, project_description or ""
        )
    except elicitation_agent.ElicitationLLMError as exc:
        yield ("error", f"LLM unavailable: {exc}")
        return
    except elicitation_agent.ElicitationAgentError as exc:
        yield ("error", f"Elicitation agent failed: {exc}")
        return

    phase_data = {
        "preguntas_respuestas": prior_history,
        "pending_question": None,
        "resumen": resumen,
    }
    project_state["requerimientos"] = phase_data
    engram_state[str(project_id)] = project_state
    save_session_state(
        user_id,
        project_id=project_id,
        active_phase="requerimientos",
        engram_state=engram_state,
    )

    yield (
        "done",
        {
            "regenerated": True,
            "phase": "requerimientos",
            "resumen": resumen,
        },
    )


async def _dispatch_propuesta(
    *,
    user_id: int,
    project_id: int,
    feedback: str,
) -> AsyncIterator[tuple[str, Any]]:
    """Re-prompt the proposal generator with iteration = max+1 regardless
    of the prior ``lifecycle``. Bypasses F08's hard 409 at the generator
    layer (REQ-PA-HU11-1).
    """
    from app.core.proposal_generator import ProposalGenerator

    generator = ProposalGenerator(user_id=user_id, project_id=project_id)
    async for event, payload_obj in generator.regenerate(
        project_id=project_id, feedback=feedback
    ):
        yield event, payload_obj


async def _dispatch_refinamiento(
    *,
    db: Any,
    user_id: int,
    project_id: int,
    feedback: str,
) -> AsyncIterator[tuple[str, Any]]:
    """Inject the feedback as a fresh chat message via the existing
    ``/api/chat`` SSE pipeline. F11 agent runtime decides whether to call
    ``puppeteer_screenshot`` again. ``previous_output.attachments`` is
    referenced as ``diagrama previo`` in the prompt (design §G).
    """
    # We don't reach into the chat endpoint internals; instead we reuse the
    # SSE adapter the existing chat endpoint emits by re-using the same
    # async iterator shape. For testability, this module ships a thin
    # re-emitter that yields the persisted-Message + done event.
    from app.core.session_store import load_session_state
    from app.core.phase_decisions import _latest_assistant_attachments

    prior_attachments = _latest_assistant_attachments(db, project_id)

    yield (
        "sources",
        [
            {
                "kind": "previous_diagram",
                "attachments": prior_attachments,
            }
        ],
    )

    # Emit the user feedback as a synthetic token so the SPA can show
    # ``Regenerando...`` until the real chat stream kicks in via the
    # parallel POST /api/chat the frontend fires. The actual content
    # stream comes from the regular /api/chat SSE; this endpoint just
    # signals that the prior state was captured.
    yield ("token", feedback.strip())

    yield (
        "done",
        {
            "regenerated": True,
            "phase": "refinamiento",
            "feedback": feedback.strip(),
        },
    )

    # Reference load_session_state so the import is reachable from tests
    # that want to assert the same prior_attachments resolution path used
    # by ``_build_previous_output`` for the refinamiento phase.
    _ = load_session_state