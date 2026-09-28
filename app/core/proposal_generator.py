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
from app.core.project_context import load_documents_text, load_requirements_text
from app.core.rag import similarity_search
from app.models import InteractionLog, Proposal, ProposalApproval, UserSession
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

# En la fase de propuesta YA NO se usa RAG_MIN_SIMILARITY como corte. La
# consulta se arma con el nombre/descripcion/requerimientos del proyecto, asi
# que siempre esta dentro del dominio: en vez de descartar candidatos por un
# umbral fijo (que con multilingual-e5-small dejaba la lista vacia), se trae
# de la base los PROPOSAL_RAG_TOP_N patrones mas cercanos. El umbral sigue
# vigente en el chat (app/api/chat.py), donde si hay preguntas fuera de tema.
#   PROPOSAL_RAG_TOP_N           patrones distintos que se citan (default 3)
#   PROPOSAL_RAG_CANDIDATE_CHUNKS chunks que se piden a PGVector antes de
#                                agrupar por patron (default 20)
#   PROPOSAL_RAG_MIN_SIMILARITY  piso opcional; 0.0 = sin piso (default)
PROPOSAL_RAG_TOP_N = int(os.getenv("PROPOSAL_RAG_TOP_N", "3"))
PROPOSAL_RAG_CANDIDATE_CHUNKS = int(os.getenv("PROPOSAL_RAG_CANDIDATE_CHUNKS", "20"))
PROPOSAL_RAG_MIN_SIMILARITY = float(os.getenv("PROPOSAL_RAG_MIN_SIMILARITY", "0.0"))

# Tope de caracteres de la propuesta previa que se le pasa al LLM al iterar.
# Antes eran 1500: una propuesta completa mide 5000+, asi que el modelo nunca
# veia la parte donde estaba lo que el usuario queria cambiar.
PRIOR_PROPOSAL_MAX_CHARS = int(os.getenv("PROPOSAL_PRIOR_MAX_CHARS", "12000"))

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
          1. ``("sources", list[dict])`` -- metadata de los ``PROPOSAL_RAG_TOP_N``
             patrones mas relevantes (uno por patron, sin umbral de
             similitud). Always emitted, even when empty.
          2. ``("token", str)`` -- one per LLM token. Many events.
          3. ``("done", {"proposal_id": int, "citations": list[dict],
             "iteration": int})`` --
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

        # 2b. Contexto del proyecto que antes NO llegaba al prompt: el resumen
        # de requerimientos aprobado y el texto de los PDF/MD subidos.
        requirements_text = await asyncio.to_thread(
            load_requirements_text, self.user_id, effective_project_id
        )
        documents_text, document_names = await asyncio.to_thread(
            load_documents_text, self.user_id, effective_project_id
        )
        logger.info(
            "Proposal context project_id=%s requirements_chars=%s documents=%s",
            effective_project_id,
            len(requirements_text),
            document_names,
        )

        # 3. Build summary query for RAG (project name + description + feedback
        # + requerimientos, para que los patrones se elijan por lo que el
        # usuario realmente pidió y no solo por el nombre del proyecto).
        summary_query = _build_summary_query(
            project.name,
            project.description,
            feedback,
            prior_content,
            requirements_text,
        )

        # 4. Retrieve patterns from PGVector.
        try:
            docs = await asyncio.to_thread(
                _retrieve_patterns, summary_query, self.user_id
            )
        except Exception as exc:  # RAG should never block generation
            # logger.exception (con traceback): antes era un warning de una
            # linea y un fallo de PGVector/embeddings quedaba disfrazado de
            # "Sin contexto recuperado" sin dejar pista de la causa real.
            logger.exception(
                "RAG retrieval failed for project_id=%s user_id=%s: %s",
                effective_project_id,
                self.user_id,
                exc,
            )
            docs = []

        citations = _select_citations(docs)
        logger.info(
            "Proposal RAG project_id=%s candidates=%s cited=%s top=%s",
            effective_project_id,
            len(docs),
            len(citations),
            [
                (c.get("pattern_name"), round(c.get("similarity") or 0.0, 3))
                for c in citations
            ],
        )
        if not docs:
            logger.warning(
                "Proposal RAG devolvio 0 candidatos para project_id=%s: revisa que "
                "architect_pattern_chunks tenga filas con embedding "
                "(python scripts/seed_patterns.py)",
                effective_project_id,
            )
        yield ("sources", citations)

        # 5. Build structured prompt and acquire LLM model.
        prompt = _build_prompt(
            citations=citations,
            prior_content=prior_content,
            feedback=feedback,
            project_name=project.name,
            description=project.description,
            requirements_text=requirements_text,
            documents_text=documents_text,
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
            proposal_id, interaction_id, saved_iteration = await asyncio.to_thread(
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
            saved_iteration,
            latency_ms,
        )

        # 9. Final done event with the canonical citations payload.
        yield (
            "done",
            {
                "proposal_id": proposal_id,
                "citations": citations,
                "iteration": saved_iteration,
            },
        )


# --- Pure helpers ---------------------------------------------------------


def _select_citations(
    docs: list[Document],
    top_n: int | None = None,
    min_similarity: float | None = None,
) -> list[dict]:
    """Elige los patrones mas relevantes y los proyecta al payload de citations.

    No aplica el umbral ``RAG_MIN_SIMILARITY``: ordena por similitud, se queda
    con un solo chunk por patron (el mejor) y devuelve los ``top_n`` primeros.
    Solo descarta por similitud si se configura un piso explicito
    (``PROPOSAL_RAG_MIN_SIMILARITY`` > 0).
    """
    limit = PROPOSAL_RAG_TOP_N if top_n is None else top_n
    floor = PROPOSAL_RAG_MIN_SIMILARITY if min_similarity is None else min_similarity

    ranked = sorted(
        docs,
        key=lambda doc: doc.metadata.get("similarity") or 0.0,
        reverse=True,
    )

    citations: list[dict] = []
    seen: set = set()
    for doc in ranked:
        if len(citations) >= limit:
            break
        similarity = doc.metadata.get("similarity") or 0.0
        if similarity < floor:
            continue
        key = doc.metadata.get("pattern_id")
        if key is None:
            key = doc.metadata.get("pattern_name")
        if key is not None:
            if key in seen:
                continue
            seen.add(key)
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
    # Se piden varios chunks porque un mismo patron tiene varios; luego
    # ``_select_citations`` agrupa por patron y corta en PROPOSAL_RAG_TOP_N.
    docs, _metrics = similarity_search(
        query=query,
        user_id=user_id,
        k=PROPOSAL_RAG_CANDIDATE_CHUNKS,
        scope="patterns",
    )
    return docs


def _build_summary_query(
    project_name: str,
    description: str | None,
    feedback: str | None,
    prior_content: str | None,
    requirements_text: str | None = None,
) -> str:
    """Concatenate project metadata + (optional) feedback into a RAG query."""
    parts = [project_name or "proyecto"]
    if description:
        parts.append(description)
    if requirements_text:
        parts.append(requirements_text[:1500])
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
    description: str | None = None,
    requirements_text: str | None = None,
    documents_text: str | None = None,
) -> str:
    """Compose the structured prompt that drives the LLM to produce 3 sections."""
    if citations:
        context_blocks = []
        for index, cite in enumerate(citations, start=1):
            context_blocks.append(
                f"[{index}] {cite.get('pattern_name')}\n{cite.get('snippet') or ''}"
            )
        context_section = "\n\n".join(context_blocks)
        candidates_intro = (
            "Patrones candidatos (son los mas cercanos de la base de conocimiento; "
            "usa solo los que apliquen al proyecto y cita el numero entre corchetes "
            "donde corresponda):\n"
        )
    else:
        context_section = "No se recuperaron patrones de la base de conocimiento."
        # Sin contexto NO se pide citar con [n]: el modelo se inventaba
        # referencias [1]..[6] que no existian.
        candidates_intro = (
            "No hay patrones recuperados de la base de conocimiento. Propon los "
            "patrones que apliquen con tu conocimiento general y NO uses numeros "
            "entre corchetes ni afirmes que provienen de la base de conocimiento.\n"
        )

    # La propuesta previa va COMPLETA (antes se cortaba a 1500 chars y el LLM
    # nunca veia la parte que el usuario queria cambiar) y el feedback va
    # despues, como instruccion de maxima prioridad y con reglas explicitas:
    # sin eso el modelo regeneraba desde cero y ignoraba el cambio.
    prior_section = ""
    if prior_content:
        prior_section = (
            "\n\nPropuesta previa (es la base sobre la que trabajas; NO la "
            "reescribas desde cero):\n"
            f"{prior_content[:PRIOR_PROPOSAL_MAX_CHARS]}\n"
        )

    feedback_section = ""
    if feedback and feedback.strip():
        feedback_section = (
            "\n\nCAMBIOS SOLICITADOS POR EL USUARIO (prioridad maxima: pesan mas "
            "que los requerimientos, los documentos y los patrones candidatos):\n"
            f"{feedback.strip()}\n\n"
            "Reglas para aplicar los cambios:\n"
            "- Parte de la propuesta previa y conserva tal cual todo lo que el "
            "usuario no pidio cambiar.\n"
            "- Aplica cada cambio de forma literal y en TODAS las secciones donde "
            "corresponda (Componentes, Tecnologias y Patrones).\n"
            "- Si el usuario dice que quiere \"solo\" ciertas tecnologias, o pide "
            "reemplazar una por otra, ELIMINA las demas de ese aspecto; no las "
            "dejes junto a las nuevas.\n"
            "- No agregues tecnologias de ese aspecto que el usuario no nombro.\n"
        )

    project_section = ""
    if description and description.strip():
        project_section += f"Descripción: {description.strip()}\n"
    if requirements_text and requirements_text.strip():
        project_section += (
            "\nRequerimientos aprobados por el usuario (resumen de la "
            "elicitación). La propuesta DEBE respetarlos:\n"
            f"{requirements_text.strip()}\n"
        )
    if documents_text and documents_text.strip():
        project_section += (
            "\nDocumentos aportados por el usuario (actas de reunión, notas, "
            "especificaciones). Cualquier restricción que mencionen (plazos, "
            "presupuesto, equipo, tecnologías) debe reflejarse en la propuesta; "
            "si un documento contradice el resumen de requerimientos, prioriza "
            "el documento (es información más reciente):\n"
            f"{documents_text.strip()}\n"
        )

    closing_reminder = ""
    if feedback and feedback.strip():
        closing_reminder = (
            "\nRecordatorio final: la propuesta que escribas DEBE reflejar los "
            "cambios solicitados por el usuario.\n"
        )

    return (
        "Eres un arquitecto de software. Tu tarea es redactar una propuesta de "
        "arquitectura para el proyecto indicado, en español, usando markdown.\n\n"
        f"Proyecto: {project_name}\n"
        f"{project_section}"
        f"{prior_section}"
        f"{feedback_section}"
        "\nREGLA DE DECISION: tu trabajo es DECIDIR, no dejar la eleccion al "
        "usuario. Elige UNA sola opcion por aspecto (un estilo arquitectonico "
        "principal, una base de datos, un broker, un framework, etc.) y "
        "justificala en una linea con base en los requerimientos. NO ofrezcas "
        "alternativas ni uses formulas como \"X o Y\", \"X / Y\" o \"X (o Z)\"; "
        "no le pidas al usuario que elija. Si dudas, elige la mejor opcion. "
        "El usuario podra pedir cambios despues con «Modificar».\n"
        "\nFormato OBLIGATORIO (responde exactamente con estas tres secciones, "
        "en este orden, con esos encabezados):\n\n"
        "## Componentes\n- ...\n\n"
        "## Tecnologias\n- ...\n\n"
        "## Patrones\n- ...\n\n"
        f"{candidates_intro}"
        f"{context_section}\n"
        f"{closing_reminder}"
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
) -> tuple[int, int, int]:
    """Insert proposal + interaction_log (+ approval for modify) atomically.

    Returns ``(proposal_id, interaction_id, iteration)`` for the SSE done
    payload and the Engram mirror. Idempotency on (project_id, iteration) is delegated
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

        # For modify path, freeze the prior content in a proposal_approvals row
        # BEFORE inserting the new proposal so the audit trail is intact even
        # on crash.
        if prior_proposal_id is not None and prior_content is not None:
            prior_row = db.get(Proposal, prior_proposal_id)
            if prior_row is not None:
                approval = ProposalApproval(
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
        return proposal_id, interaction_id, int(iteration)
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