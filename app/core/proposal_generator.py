"""Proposal generation boundary.

The persistence contract follows ADR-008 and the streaming transport follows
ADR-009. Slice 1 shipped the sync skeleton + slice-2 stub; slice 2 wires the
async iterator that yields SSE-ready events (`sources`, `token`, `done`).

The transport layer in ``app/api/proposals.py`` consumes this iterator and
serializes each tuple to the SSE wire format (``event: <name>\\ndata: <json>``).
Anything transport-specific (headers, ``X-Accel-Buffering: no``, response model)
lives in the router -- keeping this module pure domain logic makes the unit
tests deterministic and free of ASGI plumbing.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from time import perf_counter
from typing import Any, AsyncIterator

from langchain_core.documents import Document

from app.core.database import SessionLocal
from app.core.engram_client import EngramClient, EngramError
from app.core.llm_loader import build_langchain_model, LLMConfigError
from app.core.rag import similarity_search
from app.models import InteractionLog, Proposal, UserSession
from app.models.approval import Approval
from app.models.project import Project
from app.models.user import User

logger = logging.getLogger(__name__)

# RAG_MIN_SIMILARITY is re-declared here (and again in ``app/api/proposals.py``)
# to avoid a circular import that would happen if this module imported it from
# ``app/api/chat.py``. ``design.md`` §9 calls for hoisting this constant to
# ``app/core/rag_config.py`` as a follow-up refactor; until then, all three
# sites MUST stay in lock-step (chat.py, proposal_generator.py, proposals.py).
# See ``docs/adr/009-sse-pattern-reuse.md`` for the rationale.
RAG_MIN_SIMILARITY = 0.85

# Default maximum number of iterations per project. Mirrors the design
# (§5 + §17 #6). Per-project override is not yet implemented; the cap is read
# at request time so ops can tune it without code changes.
PROPOSAL_MAX_ITER = int(os.getenv("PROPOSAL_MAX_ITER", "5"))

# Engram port per ADR-008: the memory mirror is best-effort, never blocking
# (REQ-9 / SCN-10). Override for tests/dev with ENGRAM_URL.
_ENGRAM_URL = os.getenv("ENGRAM_URL", "http://localhost:7437")


class ProposalGenerator:
    """Async SSE-ready proposal generator.

    Constructed once per request; ``generate_stream`` is the only public
    surface the API endpoint calls. Yields ``(event_name, payload)`` tuples
    that the router serializes to SSE verbatim.
    """

    def __init__(
        self,
        user_id: int | None = None,
        project_id: int | None = None,
        session_id: int | None = None,
    ) -> None:
        # Keep the no-arg form working for the slice-1 smoke test that
        # calls ``ProposalGenerator().generate_sync(42)``; in production the
        # router always passes user_id + project_id.
        self.user_id = user_id
        self.project_id = project_id
        self.session_id = session_id

    # ------------------------------------------------------------------
    # Sync helpers (slice 1 contract; kept for tests + future non-stream use)
    # ------------------------------------------------------------------

    def generate_sync(self, project_id: int) -> dict:
        """Return the stable proposal skeleton until the LLM pipeline lands."""
        return {
            "project_id": project_id,
            "content": {"componentes": [], "tecnologias": [], "patrones": []},
            "citations": [],
            "feedback": None,
            "lifecycle": "proposed",
        }

    # ------------------------------------------------------------------
    # Async streaming (slice 2)
    # ------------------------------------------------------------------

    async def generate_stream(
        self,
        project_id: int | None = None,
        feedback: str | None = None,
        prior_proposal_id: int | None = None,
    ) -> AsyncIterator[tuple[str, Any]]:
        """Yield SSE-ready events for one proposal generation.

        Event order:
          1. ``("sources", list[dict])`` -- RAG pattern metadata filtered by
             ``RAG_MIN_SIMILARITY``. Always emitted, even when empty.
          2. ``("token", str)`` -- one per LLM token. Many events.
          3. ``("done", {"proposal_id": int, "citations": list[dict]})`` --
             emitted ONCE after the ``proposals`` row + ``interaction_log``
             row are committed. Citations here mirror the ``sources`` payload
             so the frontend can hydrate its store from a single source.

        On any unrecoverable failure during streaming the generator yields
        ``("error", str)`` exactly once and stops. The DB write is skipped
        so the user can retry without leaving orphan ``proposed`` rows.
        """
        effective_project_id = project_id if project_id is not None else self.project_id
        if effective_project_id is None:
            yield ("error", "project_id is required")
            return
        if self.user_id is None:
            yield ("error", "user_id is required to generate proposals")
            return

        started_at = perf_counter()

        # 1. Load project + session (ownership + FK).
        try:
            project, session_id = await asyncio.to_thread(
                _load_project_and_session, self.user_id, effective_project_id
            )
        except _ProposalDomainError as exc:
            yield ("error", str(exc))
            return

        # 2. Resolve prior proposal (only for modify path).
        prior_content: str | None = None
        prior_iteration = 0
        if prior_proposal_id is not None:
            try:
                prior_content, prior_iteration = await asyncio.to_thread(
                    _load_prior_proposal, self.user_id, prior_proposal_id
                )
            except _ProposalDomainError as exc:
                yield ("error", str(exc))
                return

        next_iteration = prior_iteration + 1 if prior_iteration else None

        # 3. Build summary query for RAG (project name + description + feedback).
        summary_query = _build_summary_query(
            project.name, project.description, feedback, prior_content
        )

        # 4. Retrieve patterns from PGVector.
        try:
            docs = await asyncio.to_thread(
                _retrieve_patterns, summary_query, self.user_id
            )
        except Exception as exc:  # RAG should never block generation
            logger.warning(
                "RAG retrieval failed for project_id=%s user_id=%s: %s",
                effective_project_id,
                self.user_id,
                exc,
            )
            docs = []

        citations = _filter_citations(docs)
        yield ("sources", citations)

        # 5. Build structured prompt and acquire LLM model.
        prompt = _build_prompt(
            citations=citations,
            prior_content=prior_content,
            feedback=feedback,
            project_name=project.name,
        )

        try:
            model = await asyncio.to_thread(build_langchain_model, self.user_id)
        except LLMConfigError as exc:
            yield ("error", str(exc))
            return

        # 6. Stream LLM tokens + accumulate the full markdown.
        full_markdown_chunks: list[str] = []
        try:
            async for event in model.astream(prompt):
                chunk = getattr(event, "content", None)
                if chunk:
                    full_markdown_chunks.append(chunk)
                    yield ("token", chunk)
        except Exception as exc:
            logger.warning(
                "LLM stream failed for project_id=%s user_id=%s: %s",
                effective_project_id,
                self.user_id,
                exc,
            )
            yield ("error", f"LLM stream failed: {exc}")
            return

        full_markdown = "".join(full_markdown_chunks)
        if not full_markdown.strip():
            # LLM emitted nothing useful -- treat as a hard error so the
            # frontend can show a banner and the user can retry without an
            # empty ``proposed`` row confusing the lifecycle.
            yield ("error", "LLM returned no content")
            return

        # 7. Persist the proposal + interaction log + (if modify) approval.
        try:
            proposal_id, interaction_id = await asyncio.to_thread(
                _persist_proposal_and_log,
                session_id=session_id,
                project_id=effective_project_id,
                iteration=next_iteration,
                prior_iteration=prior_iteration,
                prior_proposal_id=prior_proposal_id,
                prior_content=prior_content,
                markdown=full_markdown,
                citations=citations,
                feedback=feedback,
            )
        except Exception as exc:
            logger.exception(
                "Failed to persist proposal for project_id=%s user_id=%s: %s",
                effective_project_id,
                self.user_id,
                exc,
            )
            yield ("error", f"Failed to persist proposal: {exc}")
            return

        # 8. Best-effort Engram mirror (REQ-9 / SCN-10 -- never blocks).
        await _engram_mirror(
            session_id=session_id,
            proposal_id=proposal_id,
            interaction_id=interaction_id,
            markdown=full_markdown,
        )

        latency_ms = int((perf_counter() - started_at) * 1000)
        logger.info(
            "Proposal persisted project_id=%s proposal_id=%s iteration=%s latency_ms=%s",
            effective_project_id,
            proposal_id,
            next_iteration or 1,
            latency_ms,
        )

        # 9. Final done event with the canonical citations payload.
        yield (
            "done",
            {
                "proposal_id": proposal_id,
                "citations": citations,
            },
        )


# --- Pure helpers ---------------------------------------------------------


def _is_relevant(doc: Document) -> bool:
    """Pattern must clear the RAG similarity threshold (see RAG_MIN_SIMILARITY)."""
    similarity = doc.metadata.get("similarity") or 0.0
    return similarity >= RAG_MIN_SIMILARITY


def _filter_citations(docs: list[Document]) -> list[dict]:
    """Project RAG documents to the citations payload the SSE contract expects."""
    citations: list[dict] = []
    for doc in docs:
        if not _is_relevant(doc):
            continue
        citations.append(
            {
                "pattern_id": doc.metadata.get("pattern_id"),
                "pattern_name": doc.metadata.get("pattern_name"),
                "similarity": doc.metadata.get("similarity"),
                "snippet": (doc.page_content or "")[:240],
            }
        )
    return citations


def _retrieve_patterns(query: str, user_id: int) -> list[Document]:
    """Wrap ``similarity_search(scope='patterns')`` so failures don't break the stream."""
    docs, _metrics = similarity_search(
        query=query,
        user_id=user_id,
        k=5,
        scope="patterns",
    )
    return docs


def _build_summary_query(
    project_name: str,
    description: str | None,
    feedback: str | None,
    prior_content: str | None,
) -> str:
    """Concatenate project metadata + (optional) feedback into a RAG query."""
    parts = [project_name or "proyecto"]
    if description:
        parts.append(description)
    if feedback:
        parts.append(feedback)
    if prior_content:
        parts.append(prior_content[:500])
    return "\n".join(parts)


def _build_prompt(
    citations: list[dict],
    prior_content: str | None,
    feedback: str | None,
    project_name: str,
) -> str:
    """Compose the structured prompt that drives the LLM to produce 3 sections."""
    if citations:
        context_blocks = []
        for index, cite in enumerate(citations, start=1):
            context_blocks.append(
                f"[{index}] {cite.get('pattern_name')}\n{cite.get('snippet') or ''}"
            )
        context_section = "\n\n".join(context_blocks)
    else:
        context_section = "No se recuperaron patrones relevantes."

    feedback_section = ""
    if feedback:
        feedback_section = (
            f"\n\nFeedback del usuario para iterar:\n{feedback.strip()}\n"
        )

    prior_section = ""
    if prior_content:
        prior_section = (
            "\n\nPropuesta previa (a mejorar):\n"
            f"{prior_content[:1500]}\n"
        )

    return (
        "Eres un arquitecto de software. Tu tarea es redactar una propuesta de "
        "arquitectura para el proyecto indicado, en español, usando markdown.\n\n"
        f"Proyecto: {project_name}\n"
        f"{feedback_section}"
        f"{prior_section}"
        "\nFormato OBLIGATORIO (responde exactamente con estas tres secciones, "
        "en este orden, con esos encabezados):\n\n"
        "## Componentes\n- ...\n\n"
        "## Tecnologias\n- ...\n\n"
        "## Patrones\n- ...\n\n"
        "Patrones candidatos (usa solo los que apliquen; cita el numero entre "
        "corchetes donde corresponda):\n"
        f"{context_section}\n"
    )


class _ProposalDomainError(Exception):
    """Distinguished from generic exceptions so the SSE error message is clean."""


def _load_project_and_session(user_id: int, project_id: int) -> tuple[Project, int]:
    """Load project (ownership-checked) and resolve/create the user's session.

    Returns (project, session_id). Raises ``_ProposalDomainError`` with a
    user-facing Spanish message on failure -- the message bubbles straight
    out as the SSE ``error`` event.
    """
    db = SessionLocal()
    try:
        project = (
            db.query(Project)
            .filter(Project.id == project_id, Project.user_id == user_id)
            .first()
        )
        if project is None:
            exists = db.query(Project).filter(Project.id == project_id).first()
            if exists:
                raise _ProposalDomainError("No tienes acceso a este proyecto")
            raise _ProposalDomainError("Proyecto no encontrado")

        # Sessions are 1:1 with users (UserSession.user_id is unique).
        session = (
            db.query(UserSession).filter(UserSession.user_id == user_id).first()
        )
        if session is None:
            session = UserSession(
                user_id=user_id,
                project_id=project_id,
                active_phase=project.current_phase,
            )
            db.add(session)
            db.commit()
            db.refresh(session)

        return project, session.id
    except _ProposalDomainError:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise _ProposalDomainError(f"No se pudo cargar el proyecto: {exc}") from exc
    finally:
        db.close()


def _load_prior_proposal(user_id: int, proposal_id: int) -> tuple[str, int]:
    """Load a prior proposal (ownership-checked) for the modify path.

    Returns ``(content_markdown, iteration)`` where content_markdown is the
    prior row's content rendered as a string for the prompt.
    """
    db = SessionLocal()
    try:
        proposal = (
            db.query(Proposal)
            .filter(Proposal.id == proposal_id)
            .first()
        )
        if proposal is None:
            raise _ProposalDomainError("Propuesta previa no encontrada")

        project = (
            db.query(Project)
            .filter(Project.id == proposal.project_id, Project.user_id == user_id)
            .first()
        )
        if project is None:
            raise _ProposalDomainError("No tienes acceso a esta propuesta")

        content = proposal.content
        if isinstance(content, dict):
            content_markdown = json.dumps(content, ensure_ascii=False)
        else:
            content_markdown = str(content)

        return content_markdown, int(proposal.iteration)
    except _ProposalDomainError:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise _ProposalDomainError(f"No se pudo cargar la propuesta previa: {exc}") from exc
    finally:
        db.close()


def _persist_proposal_and_log(
    *,
    session_id: int,
    project_id: int,
    iteration: int | None,
    prior_iteration: int,
    prior_proposal_id: int | None,
    prior_content: str | None,
    markdown: str,
    citations: list[dict],
    feedback: str | None,
) -> tuple[int, int]:
    """Insert proposal + interaction_log (+ approval for modify) atomically.

    Returns ``(proposal_id, interaction_id)`` for the SSE done payload and
    the Engram mirror. Idempotency on (project_id, iteration) is delegated
    to the DB UNIQUE constraint -- a duplicate INSERT raises IntegrityError
    which the caller turns into a 409.
    """
    db = SessionLocal()
    try:
        if iteration is None:
            max_iter = (
                db.query(Proposal)
                .filter(Proposal.project_id == project_id)
                .order_by(Proposal.iteration.desc())
                .first()
            )
            iteration = (max_iter.iteration + 1) if max_iter else 1

        if iteration > PROPOSAL_MAX_ITER:
            raise _ProposalDomainError(
                f"Has alcanzado el máximo de iteraciones ({PROPOSAL_MAX_ITER})"
            )

        # For modify path, freeze the prior content in an approvals row BEFORE
        # inserting the new proposal so the audit trail is intact even on crash.
        if prior_proposal_id is not None and prior_content is not None:
            prior_row = db.get(Proposal, prior_proposal_id)
            if prior_row is not None:
                approval = Approval(
                    proposal_id=prior_proposal_id,
                    decision="modified",
                    previous_output=prior_row.content,
                )
                db.add(approval)

        proposal = Proposal(
            session_id=session_id,
            project_id=project_id,
            iteration=iteration,
            content=markdown,
            citations=citations,
            feedback=feedback,
            lifecycle="proposed",
        )
        db.add(proposal)
        db.flush()  # assigns proposal.id without committing yet

        action_type = "modify" if prior_proposal_id is not None else "generate"
        log = InteractionLog(
            session_id=session_id,
            project_id=project_id,
            phase="propuesta",
            action_type=action_type,
            comment=feedback,
            prompt=_build_prompt(
                citations=citations,
                prior_content=prior_content,
                feedback=feedback,
                project_name="",  # we don't store the project name in the log
            )[:65000],
            response=markdown[:65000],
            latency_ms=None,
            tokens_used=None,
        )
        db.add(log)
        db.flush()

        proposal_id = int(proposal.id)
        interaction_id = int(log.id)

        db.commit()
        return proposal_id, interaction_id
    except _ProposalDomainError:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise _ProposalDomainError(f"No se pudo persistir la propuesta: {exc}") from exc
    finally:
        db.close()


async def _engram_mirror(
    *,
    session_id: int,
    proposal_id: int,
    interaction_id: int,
    markdown: str,
) -> None:
    """Best-effort Engram mirror; never blocks the user (REQ-9 / SCN-10)."""
    client = EngramClient(base_url=_ENGRAM_URL, timeout=2.0)

    def _save() -> None:
        client.save_observation(
            session_id=str(session_id),
            project=os.getenv("ENGRAM_PROJECT", "arch-agent"),
            title=f"proposal {proposal_id} generated",
            content=markdown[:4000],
            observation_type="decision",
        )

    try:
        await asyncio.to_thread(_save)
    except EngramError as exc:
        # ConnectionError / URLError / OSErrors all surface here -- per ADR-008
        # we log and continue. The SSE ``done`` event still fires normally.
        logger.warning(
            "Engram mirror failed for proposal_id=%s interaction_id=%s: %s",
            proposal_id,
            interaction_id,
            exc,
        )
    except Exception as exc:  # noqa: BLE001 -- best-effort must swallow all
        logger.warning(
            "Unexpected Engram mirror error for proposal_id=%s: %s",
            proposal_id,
            exc,
        )