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
import re
import threading
import unicodedata
from contextlib import aclosing
from time import perf_counter
from typing import Any, AsyncIterator, Awaitable, TypeVar

from langchain_core.documents import Document
from sqlalchemy import text

from app.core.database import SessionLocal
from app.core.engram_client import EngramClient, EngramError
from app.core.env import env_float, env_int
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
#                                agrupar por patron (default 40)
#   PROPOSAL_RAG_MIN_SIMILARITY  piso opcional; 0.0 = sin piso (default)
PROPOSAL_RAG_TOP_N = env_int("PROPOSAL_RAG_TOP_N", 3, minimum=1)
PROPOSAL_RAG_CANDIDATE_CHUNKS = env_int("PROPOSAL_RAG_CANDIDATE_CHUNKS", 40, minimum=1)
PROPOSAL_RAG_MIN_SIMILARITY = env_float("PROPOSAL_RAG_MIN_SIMILARITY", 0.0, minimum=-1.0)

# Tope de caracteres de la propuesta previa que se le pasa al LLM al iterar.
# Antes eran 1500: una propuesta completa mide 5000+, asi que el modelo nunca
# veia la parte donde estaba lo que el usuario queria cambiar.
PRIOR_PROPOSAL_MAX_CHARS = env_int("PROPOSAL_PRIOR_MAX_CHARS", 12000, minimum=0)

# F19 (HU: primera propuesta en < 5 min). Presupuesto total desde que el
# usuario pide la propuesta hasta que se guarda. Aplica a TODAS las etapas
# (contexto, retrieval, LLM y guardado): si se agota, la generacion se corta con
# un error claro y NO se persiste (el usuario puede reintentar).
# PROPOSAL_MAX_SECONDS=0 lo desactiva; un valor vacío, no numérico o negativo
# vuelve al default (300) con un warning en vez de impedir el arranque.
PROPOSAL_MAX_SECONDS = env_float("PROPOSAL_MAX_SECONDS", 300.0, minimum=0.0)
# Parte del final del presupuesto reservada para guardar. Las etapas de trabajo
# (contexto, retrieval, LLM) deben terminar antes de ``MAX - reserva``: asi una
# propuesta ya completa no se pierde por unos segundos de guardado y el total
# sigue sin pasar del tope. Nunca supera el 20 % del tope.
PROPOSAL_SAVE_RESERVE_S = env_float("PROPOSAL_SAVE_RESERVE_S", 10.0, minimum=0.0)
# Longitud tipica (caracteres) de una propuesta completa: solo se usa para
# estimar el porcentaje del evento ``progress`` mientras llegan tokens.
PROPOSAL_EXPECTED_CHARS = env_int("PROPOSAL_EXPECTED_CHARS", 6000, minimum=0)
# Separacion minima entre eventos ``progress`` durante el streaming de tokens.
PROPOSAL_PROGRESS_INTERVAL_S = env_float("PROPOSAL_PROGRESS_INTERVAL_S", 1.0, minimum=0.0)

# Porcentaje al inicio de cada etapa. La etapa "generating" avanza de
# _GEN_START a _GEN_END segun los caracteres recibidos.
_PROGRESS_STAGES = {
    "context": (3, "Cargando el contexto del proyecto"),
    "retrieval": (12, "Buscando patrones de arquitectura relevantes"),
    "generating": (20, "Redactando la propuesta"),
    "saving": (95, "Guardando la propuesta"),
}
_GEN_START, _GEN_END = 20, 92

# Default maximum number of iterations per project. Mirrors the design
# (§5 + §17 #6). Per-project override is not yet implemented; the cap is read
# at request time so ops can tune it without code changes.
PROPOSAL_MAX_ITER = env_int("PROPOSAL_MAX_ITER", 5, minimum=1)

# Engram port per ADR-008: the memory mirror is best-effort, never blocking
# (REQ-9 / SCN-10). Override for tests/dev with ENGRAM_URL.
_ENGRAM_URL = os.getenv("ENGRAM_URL", "http://localhost:7437")


class _GenerationTimeout(Exception):
    """Se agoto PROPOSAL_MAX_SECONDS; distinto de un timeout interno del cliente LLM."""

    def __init__(self, stage: str = "") -> None:
        super().__init__(stage)
        self.stage = stage


class _PersistCancelled(Exception):
    """El cliente cancelo (o se agoto el tiempo) antes de confirmar el guardado."""


_T = TypeVar("_T")

# Tolerancia al comparar relojes: el timer de asyncio puede disparar unos ms
# antes de que ``perf_counter`` llegue al deadline (en Windows la resolucion del
# reloj es ~15 ms) y eso se vería como un TimeoutError "ajeno".
_DEADLINE_TOLERANCE_S = 0.05
_engram_tasks: set[asyncio.Task[None]] = set()


async def _within_budget(
    awaitable: Awaitable[_T], deadline: float | None, stage: str = ""
) -> _T:
    """Espera ``awaitable`` sin pasarse de ``deadline`` (reloj ``perf_counter``).

    ``deadline=None`` = sin tope. Si el tiempo se agota lanza
    ``_GenerationTimeout``; un ``TimeoutError`` que ocurra ANTES del deadline
    (p. ej. el de un cliente HTTP) se propaga tal cual para que lo trate la
    etapa que corresponda.

    Con ``asyncio.to_thread`` el hilo no se puede matar: se deja de esperar y
    termina solo. Es seguro para las lecturas (contexto, retrieval); el guardado
    se acota ademas en la base de datos y recibe un ``threading.Event`` de
    cancelacion que comprueba justo antes del ``commit`` (ver
    ``_persist_proposal_and_log``).
    """
    if deadline is None:
        return await awaitable
    remaining = deadline - perf_counter()
    if remaining <= 0:
        close = getattr(awaitable, "close", None)
        if close is not None:  # evita "coroutine was never awaited"
            close()
        raise _GenerationTimeout(stage)
    try:
        # timeout_at evita crear una Task extra por cada token en Python 3.11.
        # El reloj de asyncio no es perf_counter, asi que trasladamos el margen.
        loop = asyncio.get_running_loop()
        async with asyncio.timeout_at(loop.time() + remaining):
            return await awaitable
    except asyncio.TimeoutError:
        if perf_counter() >= deadline - _DEADLINE_TOLERANCE_S:
            raise _GenerationTimeout(stage) from None
        raise


def _save_reserve_s() -> float:
    """Segundos del final del presupuesto reservados para guardar (0 = sin tope)."""
    if PROPOSAL_MAX_SECONDS <= 0:
        return 0.0
    return min(PROPOSAL_SAVE_RESERVE_S, PROPOSAL_MAX_SECONDS * 0.2)


def _format_duration(seconds: float) -> str:
    """``300 -> "5 min"``, ``330 -> "5 min 30 s"``, ``15 -> "15 s"``."""
    total = int(seconds)
    minutes, secs = divmod(total, 60)
    if minutes == 0:
        return f"{secs} s"
    return f"{minutes} min" if secs == 0 else f"{minutes} min {secs} s"


def _progress_event(
    stage: str,
    started_at: float,
    *,
    percent: int | None = None,
    chars: int | None = None,
) -> tuple[str, dict]:
    """Evento SSE ``progress`` (aditivo: el front viejo lo ignora)."""
    default_percent, message = _PROGRESS_STAGES[stage]
    payload: dict[str, Any] = {
        "stage": stage,
        "percent": default_percent if percent is None else percent,
        "message": message,
        "elapsed_ms": int((perf_counter() - started_at) * 1000),
        "budget_s": PROPOSAL_MAX_SECONDS or None,
    }
    if chars is not None:
        payload["chars"] = chars
    return ("progress", payload)


def _generation_percent(chars: int) -> int:
    """Porcentaje estimado (20-92) segun lo escrito; nunca llega a 100 antes de ``done``."""
    if PROPOSAL_EXPECTED_CHARS <= 0:
        return _GEN_START
    ratio = min(1.0, chars / PROPOSAL_EXPECTED_CHARS)
    return int(_GEN_START + ratio * (_GEN_END - _GEN_START))


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
          0. ``("progress", {stage, percent, message, elapsed_ms, budget_s})`` --
             F19: aparece al iniciar cada etapa (context, retrieval,
             generating, saving) y, durante la generacion, como maximo cada
             ``PROPOSAL_PROGRESS_INTERVAL_S``. Se intercala con los demas.
          1. ``("sources", list[dict])`` -- metadata de los ``PROPOSAL_RAG_TOP_N``
             patrones mas relevantes (uno por patron, sin umbral de
             similitud). Always emitted, even when empty.
          2. ``("token", str)`` -- one per LLM token. Many events.
          3. ``("done", {"proposal_id": int, "citations": list[dict],
             "iteration": int, "elapsed_ms": int})`` --
             emitted ONCE after the ``proposals`` row + ``interaction_log``
             row are committed. Citations here mirror the ``sources`` payload
             so the frontend can hydrate its store from a single source.
             ``elapsed_ms`` es el tiempo total (F19).

        On any unrecoverable failure during streaming the generator yields
        ``("error", str)`` exactly once and stops. The DB write is skipped
        so the user can retry without leaving orphan ``proposed`` rows.

        F19 -- tiempo maximo: ``PROPOSAL_MAX_SECONDS`` es un presupuesto unico
        para todas las etapas (contexto, retrieval, LLM, guardado). Las etapas
        de trabajo deben terminar antes de ``MAX - PROPOSAL_SAVE_RESERVE_S``;
        el guardado usa ese margen final. Al agotarse se emite un unico
        ``error`` y no se persiste nada. Si el cliente se desconecta
        ("Cancelar") el generador se cierra y se cierra tambien el stream del
        LLM.
        """
        effective_project_id = project_id if project_id is not None else self.project_id
        if effective_project_id is None:
            yield ("error", "project_id is required")
            return
        if self.user_id is None:
            yield ("error", "user_id is required to generate proposals")
            return

        started_at = perf_counter()
        deadline = started_at + PROPOSAL_MAX_SECONDS if PROPOSAL_MAX_SECONDS > 0 else None
        events = self._run_pipeline(
            effective_project_id, feedback, prior_proposal_id, started_at, deadline
        )
        try:
            # aclosing: si el consumidor cierra este generador (cliente
            # desconectado) se cierra de inmediato el pipeline y con el el LLM.
            async with aclosing(events):
                async for event in events:
                    yield event
        except _GenerationTimeout as exc:
            logger.warning(
                "Proposal timed out project_id=%s user_id=%s stage=%s after %ss",
                effective_project_id,
                self.user_id,
                exc.stage or "?",
                PROPOSAL_MAX_SECONDS,
            )
            limit = _format_duration(PROPOSAL_MAX_SECONDS)
            if exc.stage == "saving":
                # El hilo de la BD no se puede abortar a la fuerza: en un caso
                # extremo la fila podria llegar a guardarse despues del corte.
                yield (
                    "error",
                    f"El guardado superó el tiempo máximo ({limit}). Recarga para ver si la "
                    "propuesta quedó guardada; si no aparece, intenta de nuevo.",
                )
            else:
                yield (
                    "error",
                    f"La generación superó el tiempo máximo ({limit}) y se canceló. No se "
                    "guardó nada; intenta de nuevo o prueba con un modelo más rápido.",
                )

    async def _run_pipeline(
        self,
        effective_project_id: int,
        feedback: str | None,
        prior_proposal_id: int | None,
        started_at: float,
        deadline: float | None,
    ) -> AsyncIterator[tuple[str, Any]]:
        """Etapas de ``generate_stream``; lanza ``_GenerationTimeout`` al agotar el tope."""
        # Las etapas de trabajo terminan antes que el tope total; el guardado
        # usa el margen reservado (``_save_reserve_s``).
        work_deadline = deadline - _save_reserve_s() if deadline is not None else None
        yield _progress_event("context", started_at)

        # 1. Load project + session (ownership + FK).
        try:
            project, session_id = await _within_budget(
                asyncio.to_thread(
                    _load_project_and_session, self.user_id, effective_project_id
                ),
                work_deadline,
                "context",
            )
        except _ProposalDomainError as exc:
            yield ("error", str(exc))
            return

        # 2. Resolve prior proposal (only for modify path).
        prior_content: str | None = None
        prior_iteration = 0
        if prior_proposal_id is not None:
            try:
                prior_content, prior_iteration = await _within_budget(
                    asyncio.to_thread(
                        _load_prior_proposal, self.user_id, prior_proposal_id
                    ),
                    work_deadline,
                    "context",
                )
            except _ProposalDomainError as exc:
                yield ("error", str(exc))
                return

        next_iteration = prior_iteration + 1 if prior_iteration else None

        # 2b. Contexto del proyecto que antes NO llegaba al prompt: el resumen
        # de requerimientos aprobado y el texto de los PDF/MD subidos.
        # Las dos lecturas son independientes: se hacen a la vez.
        async def _load_context() -> tuple[str, tuple[str, list[str]]]:
            return await asyncio.gather(
                asyncio.to_thread(load_requirements_text, self.user_id, effective_project_id),
                asyncio.to_thread(load_documents_text, self.user_id, effective_project_id),
            )

        requirements_text, (documents_text, document_names) = await _within_budget(
            _load_context(), work_deadline, "context"
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
        yield _progress_event("retrieval", started_at)
        try:
            docs = await _within_budget(
                asyncio.to_thread(_retrieve_patterns, summary_query, self.user_id),
                work_deadline,
                "retrieval",
            )
        except _GenerationTimeout:
            raise  # el tope total manda: no se sigue sin contexto
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

        logger.info(
            "Proposal RAG raw project_id=%s top_chunks=%s",
            effective_project_id,
            [
                (
                    d.metadata.get("pattern_name"),
                    d.metadata.get("chunk_type"),
                    round(d.metadata.get("similarity") or 0.0, 3),
                )
                for d in sorted(
                    docs, key=lambda d: d.metadata.get("similarity") or 0.0, reverse=True
                )[:8]
            ],
        )
        explicit_text = "\n".join(
            part
            for part in (project.name, project.description, requirements_text, feedback)
            if part
        )
        citations = _select_citations(
            docs, explicit_text=explicit_text, feedback=feedback
        )
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
            model = await _within_budget(
                asyncio.to_thread(build_langchain_model, self.user_id),
                work_deadline,
                "generating",
            )
        except LLMConfigError as exc:
            yield ("error", str(exc))
            return

        # 6. Stream LLM tokens + accumulate the full markdown.
        full_markdown_chunks: list[str] = []
        finish_reason: str | None = None
        chars_received = 0
        last_progress_at = perf_counter()
        yield _progress_event("generating", started_at)
        stream = model.astream(prompt).__aiter__()
        try:
            while True:
                try:
                    # Solo es nuestro tope si de verdad se agoto el presupuesto;
                    # un timeout del cliente HTTP del LLM sigue siendo un fallo
                    # normal del stream (rama ``except Exception`` de abajo).
                    event = await _within_budget(
                        stream.__anext__(), work_deadline, "generating"
                    )
                except StopAsyncIteration:
                    break
                metadata = getattr(event, "response_metadata", None) or {}
                finish_reason = metadata.get("finish_reason") or finish_reason
                chunk = getattr(event, "content", None)
                if chunk:
                    full_markdown_chunks.append(chunk)
                    chars_received += len(chunk)
                    yield ("token", chunk)
                    now = perf_counter()
                    if now - last_progress_at >= PROPOSAL_PROGRESS_INTERVAL_S:
                        last_progress_at = now
                        yield _progress_event(
                            "generating",
                            started_at,
                            percent=_generation_percent(chars_received),
                            chars=chars_received,
                        )
        except _GenerationTimeout:
            logger.warning("Proposal LLM stream cut by time budget chars=%s", chars_received)
            raise  # lo convierte en el evento ``error`` generate_stream
        except Exception as exc:
            logger.warning(
                "LLM stream failed for project_id=%s user_id=%s: %s",
                effective_project_id,
                self.user_id,
                exc,
            )
            yield ("error", f"LLM stream failed: {exc}")
            return
        finally:
            # Cancelacion del usuario (cliente desconectado), timeout o error:
            # cerrar el stream del proveedor para dejar de consumir tokens.
            aclose = getattr(stream, "aclose", None)
            if aclose is not None:
                try:
                    await aclose()
                except Exception:  # best-effort
                    pass

        full_markdown = "".join(full_markdown_chunks)
        if not full_markdown.strip():
            # LLM emitted nothing useful -- treat as a hard error so the
            # frontend can show a banner and the user can retry without an
            # empty ``proposed`` row confusing the lifecycle.
            yield ("error", "LLM returned no content")
            return

        # Una propuesta cortada a la mitad (limite de tokens del modelo, stream
        # cerrado por el proveedor) NO se guarda: quedaria como iteracion vigente,
        # gastaria una de las PROPOSAL_MAX_ITER y la siguiente modificacion
        # partiria de un texto al que le faltan secciones.
        missing_sections = _missing_sections(full_markdown)
        if finish_reason == "length" or missing_sections:
            logger.warning(
                "Proposal incomplete project_id=%s finish_reason=%s missing=%s chars=%s",
                effective_project_id,
                finish_reason,
                missing_sections,
                len(full_markdown),
            )
            yield ("error", _incomplete_proposal_message(finish_reason, missing_sections))
            return

        # 7. Persist the proposal + interaction log + (if modify) approval.
        yield _progress_event("saving", started_at, chars=chars_received)
        # El hilo de la BD no se puede matar: ademas del tope de espera, cada
        # sentencia lleva un statement_timeout con el tiempo que queda, asi una
        # sentencia colgada se aborta en la base (rollback) en vez de guardar
        # despues de que el usuario ya vio el error.
        # ``cancel_event`` cubre el otro hueco: si el cliente cancela (o se agota
        # el tiempo) mientras el hilo ya esta guardando, ``await`` deja de esperar
        # pero el hilo sigue. El evento se marca y el hilo lo comprueba justo antes
        # del commit: hace rollback en vez de consumir una de PROPOSAL_MAX_ITER.
        cancel_event = threading.Event()
        statement_timeout_ms = (
            max(int((deadline - perf_counter()) * 1000), 500) if deadline is not None else None
        )
        try:
            proposal_id, interaction_id, saved_iteration = await _within_budget(
                asyncio.to_thread(
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
                    statement_timeout_ms=statement_timeout_ms,
                    cancel_event=cancel_event,
                ),
                deadline,
                "saving",
            )
        except (_GenerationTimeout, asyncio.CancelledError):
            # Cancelacion del cliente o tope de tiempo: que el hilo (que no se
            # puede matar) no confirme un guardado que nadie va a ver.
            cancel_event.set()
            raise
        except Exception as exc:
            logger.exception(
                "Failed to persist proposal for project_id=%s user_id=%s: %s",
                effective_project_id,
                self.user_id,
                exc,
            )
            # El detalle tecnico queda en el log; no se mezcla SQL ni wrappers
            # internos con el mensaje accionable de la interfaz.
            yield ("error", "No se pudo guardar la propuesta. Recarga para comprobar el estado e intenta de nuevo.")
            return

        # 8. Engram es estrictamente secundario: conservar una referencia fuerte
        # evita que la tarea se pierda, sin retrasar el evento done.
        mirror_task = asyncio.create_task(_engram_mirror(
            session_id=session_id,
            proposal_id=proposal_id,
            interaction_id=interaction_id,
            markdown=full_markdown,
        ))
        _engram_tasks.add(mirror_task)
        mirror_task.add_done_callback(_engram_tasks.discard)

        latency_ms = int((perf_counter() - started_at) * 1000)
        logger.info(
            "Proposal persisted project_id=%s proposal_id=%s iteration=%s latency_ms=%s",
            effective_project_id,
            proposal_id,
            saved_iteration,
            latency_ms,
        )
        if PROPOSAL_MAX_SECONDS > 0 and latency_ms > PROPOSAL_MAX_SECONDS * 1000:
            # La persistencia puede consumir el margen final: la propuesta se
            # guarda igual y se informa la latencia real.
            logger.warning(
                "Proposal over time budget project_id=%s latency_ms=%s budget_s=%s",
                effective_project_id,
                latency_ms,
                PROPOSAL_MAX_SECONDS,
            )

        # 9. Final done event with the canonical citations payload.
        yield (
            "done",
            {
                "proposal_id": proposal_id,
                "citations": citations,
                "iteration": saved_iteration,
                "elapsed_ms": latency_ms,
            },
        )


# --- Pure helpers ---------------------------------------------------------


# Complejidad operativa que exige cada patron (columna architect_patterns.
# complexity, definida en data/patterns/*.yaml). La similitud semantica sola
# no sabe si un patron es proporcional al tamano del proyecto: al ordenar los
# candidatos se le resta PROPOSAL_COMPLEXITY_PENALTY por nivel (baja=0,
# media=1, alta=2). Es un empate suave: un patron pesado con MUCHA mas
# similitud sigue ganando, y no se penaliza si el usuario lo pidio por nombre.
# Poner 0 desactiva el ajuste.
# Con multilingual-e5-small las similitudes de los patrones caen en una banda
# estrecha (~0.80-0.90), asi que 0.03 por nivel no alcanzaba para bajar a
# CQRS/microservicios en un proyecto chico: 0.08 (alta = 0.16) si, y un patron
# pesado con muchisima mas similitud, o nombrado por el usuario, aun puede ganar.
PROPOSAL_COMPLEXITY_PENALTY = env_float("PROPOSAL_COMPLEXITY_PENALTY", 0.08, minimum=0.0)
_COMPLEXITY_LEVEL = {"baja": 0, "media": 1, "alta": 2}

# La penalizacion de arriba es un empate SUAVE (ver comentario de arriba: "un
# patron pesado con muchisima mas similitud... aun puede ganar"). En la
# practica, para un proyecto chico la similitud de Microservicios suele ganarle
# a Monolito modular por mas que el margen que cubre 0.16, porque el texto de
# requerimientos describe varios subsistemas (ingesta, reportes, dashboards,
# alertas) que embeben parecido a "microservicios" aunque el equipo sea de 3
# personas. Por eso se suma una descalificacion DURA (no un ajuste de puntaje):
# si el proyecto declara equipo chico, presupuesto bajo o un MVP/prototipo, un
# patron de complejidad "alta" no puede ser el principal salvo que el usuario
# lo pida por nombre (ver _explicitly_requested) -- sin importar cuanta mas
# similitud tenga.
PROPOSAL_SMALL_TEAM_MAX = env_int("PROPOSAL_SMALL_TEAM_MAX", 4, minimum=0)
PROPOSAL_SMALL_BUDGET_USD = env_float("PROPOSAL_SMALL_BUDGET_USD", 20000.0, minimum=0.0)

_TEAM_SIZE_RE = re.compile(
    r"equipo\s+(?:de\s+)?(\d+)\s*"
    r"(?:ingenieros?|desarrolladores?|personas|devs?|full-?stack)"
)
_BUDGET_RE = re.compile(r"\$\s?(\d[\d.,]*)\s*(?:usd|dolares)?")
_SMALL_SCALE_PHRASES = (
    "mvp",
    "prototipo",
    "proyecto academico",
    "proyecto universitario",
    "equipo pequeno",
    "equipo reducido",
    "sin equipo de infraestructura dedicado",
    "infraestructura dedicado",
    "infraestructura dedicada",
    "devops dedicado",
    "equipo de operaciones dedicado",
    "presupuesto bajo",
    "presupuesto limitado",
    "presupuesto ajustado",
    "bajo presupuesto",
)


def _parse_min_budget_usd(normalized_text: str) -> float | None:
    """Menor cifra en dolares mencionada (p. ej. "entre $8,000 y $13,000" -> 8000).

    Es una heuristica: tambien puede capturar un OPEX mensual u otra cifra
    menor que no sea el presupuesto total. Eso no es un problema aqui porque
    solo se usa para decidir si el proyecto suena "chico" -- un falso
    positivo simplemente hace que la propuesta por defecto sea mas simple,
    que es el sentido seguro de equivocarse para este caso.
    """
    amounts = []
    for match in _BUDGET_RE.finditer(normalized_text):
        raw = match.group(1).replace(".", "").replace(",", "")
        if raw.isdigit():
            amounts.append(float(raw))
    return min(amounts) if amounts else None


def _small_scale_signal(explicit_text: str | None) -> bool:
    """True si el proyecto declara equipo chico, presupuesto bajo o un MVP/prototipo."""
    if not explicit_text:
        return False
    normalized = _normalize_text(explicit_text)
    if any(phrase in normalized for phrase in _SMALL_SCALE_PHRASES):
        return True
    team_match = _TEAM_SIZE_RE.search(normalized)
    if team_match and int(team_match.group(1)) <= PROPOSAL_SMALL_TEAM_MAX:
        return True
    budget = _parse_min_budget_usd(normalized)
    if budget is not None and budget <= PROPOSAL_SMALL_BUDGET_USD:
        return True
    return False


def _normalize_text(text: str | None) -> str:
    """Minusculas y sin acentos, para comparar texto libre."""
    return "".join(
        char
        for char in unicodedata.normalize("NFD", (text or "").casefold())
        if unicodedata.category(char) != "Mn"
    )


def _pattern_aliases(pattern_name: str) -> list[str]:
    """Nombres con los que un usuario suele referirse a un patron.

    "Arquitectura hexagonal (Puertos y Adaptadores)" ->
    ["arquitectura hexagonal (puertos y adaptadores)", "arquitectura hexagonal",
     "hexagonal", "puertos y adaptadores"].
    """
    normalized = _normalize_text(pattern_name)
    aliases = {normalized}
    for part in re.split(r"[()+]", normalized):
        part = part.strip()
        if len(part) < 3:
            continue
        aliases.add(part)
        aliases.add(re.sub(r"^arquitectura\s+", "", part))
        aliases.add(re.sub(r"^arquitectura\s+(?:en\s+)?", "", part))  # "capas"
        if part.startswith("monolito"):
            aliases.add("monolito")
    # "microservicios" -> tambien "microservicio"
    aliases |= {a[:-1] for a in list(aliases) if len(a) >= 8 and a.endswith("s")}
    return sorted(a for a in aliases if len(a) >= 3)


def _alias_mentions(pattern_name: str, normalized_text: str) -> list[tuple[int, int]]:
    """(inicio, fin) de cada mencion del patron (o de un alias) en el texto."""
    spans: dict[int, int] = {}
    for alias in _pattern_aliases(pattern_name):
        for match in re.finditer(r"\b" + re.escape(alias), normalized_text):
            spans[match.start()] = max(spans.get(match.start(), 0), match.end())
    return sorted(spans.items())


# Palabras sueltas que, en la misma clausula y ANTES del patron, indican que la
# mencion esta negada aunque no encaje en el patron estricto de _REJECT_CUE
# ("no cambies a microservicios", "no se si usar microservicios").
_NEGATOR = re.compile(r"\b(?:no|sin|ni|nunca|jamas|tampoco|evit\w+|nada\s+de)\b")
# Solo para REQUERIMIENTOS: nombrar un patron como posibilidad futura no es
# pedirlo ("a futuro podria migrar a microservicios").
_HEDGE = re.compile(
    r"\b(?:podria\w*|quiza\w*|tal\s+vez|eventualmente|a\s+futuro|en\s+el\s+futuro|"
    r"mas\s+adelante|a\s+largo\s+plazo|si\s+(?:el\s+sistema\s+)?crece)\b"
)


def _explicitly_requested(pattern_name: str | None, explicit_text: str | None) -> bool:
    """True si el usuario nombra el patron en sus requerimientos o cambios.

    Una mencion negada ("evitar microservicios", "sin CQRS") o solo hipotetica
    ("a futuro podria migrar a microservicios") NO cuenta como pedirlo.
    """
    if not pattern_name or not explicit_text:
        return False
    haystack = _normalize_text(explicit_text)
    return any(
        not _mention_negated(haystack, start, hedge=True)
        for start, _end in _alias_mentions(pattern_name, haystack)
    )


# Palabras que, justo antes del nombre de un patron, indican que el usuario lo
# QUIERE QUITAR ("sin CQRS", "no quiero microservicios", "cambia CQRS por X",
# "X en vez de CQRS", "cambia la arquitectura de CQRS a X"). Solo se permite
# relleno corto entre la palabra y el patron, para que "cambia la arquitectura
# a hexagonal" NO cuente como rechazo de hexagonal.
_FILLER_WORDS = (
    r"(?:(?:el|la|los|las|lo|un|una|de|del|con|al|su|tu|este|esta|ese|esa|"
    r"usar|use|uses|utilices|utilizar|usemos|usen|"
    r"hagas|hacer|implementes|implementar|apliques|aplicar|incluyas|incluir|"
    r"tengas|tener|quiero|queremos|quisiera|deseo|necesito|necesitamos|necesita|"
    r"requerimos|me\s+gusta|que|sea|sean|se|es|ser|"
    r"por\s+completo|completamente|totalmente|del\s+todo|definitivamente|ya|"
    r"patron|arquitectura|estilo|modelo|enfoque)\s+)*"
)
_REJECT_FILLER = _FILLER_WORDS
_REJECT_CUE = re.compile(
    r"(?:\b(?:sin|no|ni|nada\s+de|quita\w*|elimina\w*|remueve\w*|remover|evit\w+|"
    r"descarta\w*|deja\w*\s+de|abandona\w*|olvida\w*|reemplaza\w*|sustituye\w*|"
    r"cambia\w*(?:\s+de)?|cambio\s+de|pasa\w*\s+de|migra\w*\s+de)"
    r"|en\s+(?:vez|lugar)\s+del?)\s+" + _REJECT_FILLER + r"$"
)
# Verbos / marcas que piden el patron de forma explicita. Una mencion que no
# los tiene ni esta negada es ambigua (``None``): no se interpreta como pedido.
_WANT_CUE = re.compile(
    r"\b(?:us(?:a|ar|as|an|e|es|en|emos|ando)|utiliz\w+|utilic\w+|prefier\w+|"
    r"prefir\w+|quier\w+|quis\w+|dese(?:o|a|amos|an)|necesit\w+|requier\w+|"
    r"implement\w+|adopt\w+|aplic(?:a|ar|ue|uemos|amos)|incluy\w+|agreg\w+|"
    r"anad\w+|opt(?:a|ar|e|emos|amos)|mejor|haz\w*|hag\w+|hacer|constru\w+|"
    r"disen\w+|basa\w*|sea|sean|ser)\s+" + _FILLER_WORDS + r"$"
)
# "cambia la arquitectura a X", "cambia CQRS por X", "migra a X".
_CHANGE_TO_CUE = re.compile(
    r"\b(?:cambi\w+|pasa\w*|pasar|migr\w+|mueve\w*|mover|convert\w+|reemplaz\w+|"
    r"sustituy\w+|transform\w+)\b.*\b(?:a|por|hacia|en)\s+" + _FILLER_WORDS + r"$"
)
# "X en vez de Y": X es lo que se pide.
_WANT_SUFFIX = re.compile(r"^\W*(?:en\s+(?:vez|lugar)\s+de|en\s+reemplazo|y\s+no\b)")
_CLAUSE_BREAK = re.compile(r"[.,;:!?\n]")


def _clause_before(normalized_text: str, start: int) -> str:
    """Texto de la clausula que precede a ``start`` (max. 80 caracteres)."""
    window = normalized_text[max(0, start - 80) : start]
    return _CLAUSE_BREAK.split(window)[-1]


def _is_rejected_mention(normalized_text: str, start: int) -> bool:
    """True si la mencion que empieza en ``start`` va precedida de un rechazo."""
    return bool(_REJECT_CUE.search(_clause_before(normalized_text, start)))


def _mention_negated(normalized_text: str, start: int, *, hedge: bool = False) -> bool:
    """True si la mencion esta negada (rechazo estricto o una negacion previa).

    ``hedge=True`` tambien cuenta como no pedida la mencion hipotetica; es lo
    que se quiere para requerimientos, no para el feedback.
    """
    # "no uses CQRS sino hexagonal": lo que sigue a "sino" ya no esta negado.
    clause = re.split(r"\bsino\b", _clause_before(normalized_text, start))[-1]
    if _REJECT_CUE.search(clause) or _NEGATOR.search(clause):
        return True
    return hedge and bool(_HEDGE.search(clause))


def _mention_stance(normalized_text: str, start: int, end: int) -> str | None:
    """``"reject"``, ``"want"`` o ``None`` (ambigua) para UNA mencion en el feedback.

    Antes toda mencion no reconocida como rechazo se tomaba como ``"want"``, y
    una negacion fuera de la lista corta de relleno ("no necesitamos X",
    "elimina por completo X") terminaba pidiendo justo lo contrario. Ahora
    ``"want"`` exige una senal positiva; lo ambiguo no mueve el ranking.
    """
    clause = _clause_before(normalized_text, start)
    after_but = re.split(r"\bsino\b", clause)
    clause = after_but[-1]
    if _REJECT_CUE.search(clause):
        return "reject"
    if _NEGATOR.search(clause):
        return None
    if len(after_but) > 1:  # "... sino X"
        return "want"
    if _WANT_CUE.search(clause) or _CHANGE_TO_CUE.search(clause):
        return "want"
    if _WANT_SUFFIX.search(normalized_text[end : end + 40]):
        return "want"
    return None


def _keyword_wanted(keywords: tuple[str, ...], normalized_text: str) -> bool:
    """True si alguna keyword aparece al menos una vez SIN ser negada ni hipotetica."""
    return any(
        not _mention_negated(normalized_text, match.start(), hedge=True)
        for keyword in keywords
        for match in re.finditer(re.escape(keyword), normalized_text)
    )


def _feedback_stance(pattern_name: str | None, feedback: str | None) -> str | None:
    """Como nombra el feedback a un patron: ``"want"``, ``"reject"`` o ``None``."""
    if not pattern_name or not feedback:
        return None
    haystack = _normalize_text(feedback)
    stances = [
        _mention_stance(haystack, start, end)
        for start, end in _alias_mentions(pattern_name, haystack)
    ]
    if "want" in stances:
        return "want"
    if "reject" in stances:
        return "reject"
    return None


# Chunks que describen CUANDO NO usar un patron. Su texto menciona justo los
# casos que suelen ser el proyecto ("equipos pequenos, presupuesto limitado"),
# asi que puntuan muy alto por similitud (los embeddings no entienden la
# negacion) y terminaban eligiendo como principal al patron que menos aplica
# (p. ej. Microservicios). No cuentan como evidencia de que el patron encaja:
# solo sirven para bajarlo de posicion.
AVOID_CHUNK_TYPES = frozenset({"when_not_to_use"})


def _select_citations(
    docs: list[Document],
    top_n: int | None = None,
    min_similarity: float | None = None,
    explicit_text: str | None = None,
    feedback: str | None = None,
) -> list[dict]:
    """Elige los patrones que mejor encajan y los proyecta al payload de citations.

    No aplica el umbral ``RAG_MIN_SIMILARITY``. Por cada patron:
      * su puntaje es el del mejor chunk que habla de cuando SI usarlo
        (resumen, señales de decision, tradeoffs...); los chunks
        ``when_not_to_use`` no cuentan como evidencia a favor;
      * si su chunk ``when_not_to_use`` se parece mas al proyecto que
        cualquiera de sus chunks a favor, el proyecto cae en el caso "no usar"
        y el patron pasa detras de los que si encajan.
    Luego ordena (similitud menos una penalizacion por complejidad, salvo que
    el usuario nombre el patron en ``explicit_text``), deja un chunk por patron
    y devuelve los ``top_n`` primeros.
    Solo descarta por similitud si se configura un piso explicito
    (``PROPOSAL_RAG_MIN_SIMILARITY`` > 0).

    ``feedback`` (los cambios que pide el usuario al modificar) MANDA sobre el
    ranking: el patron que el feedback pide pasa a ser el principal aunque tenga
    menos similitud o mas complejidad, y el que el feedback quita ("sin CQRS",
    "cambia CQRS por X") no se cita. ``explicit_text`` (requerimientos) solo
    evita la penalizacion por complejidad.
    """
    limit = PROPOSAL_RAG_TOP_N if top_n is None else top_n
    floor = PROPOSAL_RAG_MIN_SIMILARITY if min_similarity is None else min_similarity

    def _sim(doc: Document) -> float:
        return doc.metadata.get("similarity") or 0.0

    def _is_avoid(doc: Document) -> bool:
        return doc.metadata.get("chunk_type") in AVOID_CHUNK_TYPES

    # Si TODOS los candidatos son "no usar" no hay evidencia a favor de nadie:
    # se conserva el comportamiento anterior en vez de devolver una lista vacia.
    use_avoid_signal = any(not _is_avoid(doc) for doc in docs)

    best_fit: dict[Any, Document] = {}
    best_avoid: dict[Any, float] = {}
    for index, doc in enumerate(docs):
        key = doc.metadata.get("pattern_id")
        if key is None:
            key = doc.metadata.get("pattern_name")
        if key is None:
            key = ("_sin_patron", index)  # sin identidad: no se deduplica

        if use_avoid_signal and _is_avoid(doc):
            best_avoid[key] = max(best_avoid.get(key, 0.0), _sim(doc))
            continue
        current = best_fit.get(key)
        if current is None or _sim(doc) > _sim(current):
            best_fit[key] = doc

    def _avoided(key: Any) -> bool:
        return key in best_avoid and best_avoid[key] > _sim(best_fit[key])

    def _score(doc: Document) -> float:
        level = _COMPLEXITY_LEVEL.get(doc.metadata.get("complexity"), 0)
        if not level or _explicitly_requested(
            doc.metadata.get("pattern_name"), explicit_text
        ):
            return _sim(doc)
        return _sim(doc) - PROPOSAL_COMPLEXITY_PENALTY * level

    stance = {
        key: _feedback_stance(doc.metadata.get("pattern_name"), feedback)
        for key, doc in best_fit.items()
    }

    # Descalificacion dura por escala del proyecto (ver comentario junto a
    # PROPOSAL_SMALL_TEAM_MAX): un patron "alta" complejidad no puede ser
    # principal en un proyecto chico salvo que el usuario lo pida por nombre
    # (stance == "want") o lo mencione explicitamente en sus requerimientos.
    small_scale = _small_scale_signal(explicit_text)

    def _scale_disqualified(key: Any) -> bool:
        if not small_scale or stance[key] == "want":
            return False
        doc = best_fit[key]
        if _COMPLEXITY_LEVEL.get(doc.metadata.get("complexity"), 0) < 2:
            return False
        return not _explicitly_requested(doc.metadata.get("pattern_name"), explicit_text)

    ordered = sorted(
        best_fit.items(),
        key=lambda item: (
            stance[item[0]] == "reject",
            stance[item[0]] != "want",
            _scale_disqualified(item[0]),
            _avoided(item[0]),
            -_score(item[1]),
        ),
    )

    citations: list[dict] = []
    for _key, doc in ordered:
        if len(citations) >= limit:
            break
        if stance[_key] == "reject":
            continue
        # Lo que el usuario pidio por nombre se cita aunque no llegue al piso.
        if stance[_key] != "want" and _sim(doc) < floor:
            continue
        citations.append(
            {
                "pattern_id": doc.metadata.get("pattern_id"),
                "pattern_name": doc.metadata.get("pattern_name"),
                "similarity": doc.metadata.get("similarity"),
                "snippet": (doc.page_content or "")[:240],
            }
        )
    # La primera coincidencia es la que el motor selecciona como sustento
    # principal de la propuesta. El resto aporta contexto, pero no se debe
    # presentar como si estuviera citado: esa distinción llega hasta la UI.
    for index, citation in enumerate(citations):
        citation["source_role"] = (
            "primary" if index == 0 else "consulted_not_cited"
        )

    return citations


_REQUIRED_HEADINGS = (
    ("Componentes", r"componentes?"),
    ("Tecnologias", r"tecnologias?"),
    ("Patrones", r"patr(?:on|ones)"),
    (
        "Justificación del patrón principal",
        r"justificacion(?:\s+del\s+patron(?:\s+principal)?)?",
    ),
)
# "Riesgo o costo" con las variantes que escribe un modelo ("Riesgos y costos",
# "Riesgo/costo", "Riesgo y costo"), o un bullet solo "Riesgo:" / "Costo:".
_RISK_OR_COST_RE = re.compile(
    r"riesgos?\s*(?:o|y|e|/|,|-)\s*costos?|^\W*(?:riesgos?|costos?)\s*:",
    re.MULTILINE,
)


def _missing_sections(markdown: str | None) -> list[str]:
    """Secciones obligatorias que faltan en la propuesta (lista vacia = completa).

    Comprueba los cuatro encabezados ``##`` del formato (tolerando singular/
    plural, acentos y negritas) y que la justificacion llegue hasta su ultimo
    punto (riesgo o costo), que es lo primero que se pierde cuando la respuesta
    se corta. El riesgo se busca solo DESPUES del encabezado de la
    justificacion para no confundirlo con otra mencion de la propuesta.
    """
    normalized = _normalize_text(markdown)
    missing: list[str] = []
    justification_start: int | None = None
    for label, pattern in _REQUIRED_HEADINGS:
        match = re.search(
            r"^[ \t]*#{1,6}[ \t]*\**[ \t]*" + pattern + r"\b", normalized, re.MULTILINE
        )
        if match is None:
            missing.append(label)
        elif label == "Justificación del patrón principal":
            justification_start = match.end()
    if justification_start is not None and not _RISK_OR_COST_RE.search(
        normalized, justification_start
    ):
        missing.append("Riesgo o costo")
    return missing


def _incomplete_proposal_message(
    finish_reason: str | None, missing_sections: list[str]
) -> str:
    """Mensaje de error segun la causa real de una propuesta incompleta."""
    missing = f" (faltan: {', '.join(missing_sections)})" if missing_sections else ""
    if finish_reason == "length":
        return (
            "El modelo se quedó sin tokens de salida y la propuesta quedó "
            f"incompleta{missing}. No se guardó ni consumió una iteración; "
            "sube el límite de tokens de salida del modelo e intenta de nuevo."
        )
    return (
        "El modelo dejó la propuesta incompleta: no incluyó todas las "
        f"secciones obligatorias{missing}. No se guardó ni consumió una "
        "iteración; intenta de nuevo."
    )


def _strip_secondary_references(text: str | None) -> str:
    """Quita la linea ``- Consultados no citados: ...`` de una propuesta previa.

    Esa linea lista patrones que solo se consultaron como contexto. Si se
    dejara, un patron secundario (p. ej. Microservicios) activaria su
    estructura base en cada iteracion aunque nunca se haya elegido.
    """
    if not text:
        return ""
    return "\n".join(
        line
        for line in text.splitlines()
        if "consultados no citados" not in line.casefold()
    )


_BASELINE_MICROSERVICES = (
    "ESTRUCTURA BASE SELECCIONADA: microservicios (sujeta a las "
    "RESTRICCIONES DE VIABILIDAD).\n"
    "Si el presupuesto, el equipo o el alcance son pequenos o no estan "
    "definidos, aplica la version MINIMA: 2 o 3 servicios por dominio "
    "de negocio, cada uno con su propia base de datos logica, "
    "comunicacion sincrona simple (HTTP/REST), sin broker de eventos y "
    "con logs basicos en lugar de observabilidad centralizada; explica "
    "en 'Riesgo o costo' por que no se propone la version completa.\n"
    "Version completa (solo si presupuesto y equipo la justifican): "
    "incluye un API Gateway como punto de entrada, servicios de negocio "
    "desacoplados por dominio, una base de datos privada por servicio, "
    "comunicacion asincrona mediante broker de eventos cuando haya "
    "integracion entre dominios y observabilidad centralizada.\n"
    "En ambos casos no modeles una unica base de datos compartida ni un "
    "monolito disfrazado de servicios.\n"
    "El diagrama posterior debe poder mostrar Cliente -> (API Gateway, "
    "si se incluye) -> Servicios y las dependencias de cada servicio "
    "con su propia base de datos usando esos mismos nombres.\n"
)
_BASELINE_EVENT_DRIVEN = (
    "ESTRUCTURA BASE SELECCIONADA: orientada a eventos (sujeta a las "
    "RESTRICCIONES DE VIABILIDAD).\n"
    "Incluye productores, broker o bus de eventos, consumidores "
    "independientes, contratos de evento versionados y manejo de "
    "reintentos/idempotencia. Con presupuesto o equipo pequenos, limita "
    "los eventos a los flujos que realmente lo necesiten y prefiere un "
    "broker gestionado o de bajo costo.\n"
)
_BASELINE_HEXAGONAL = (
    "ESTRUCTURA BASE SELECCIONADA: arquitectura hexagonal.\n"
    "Distingue dominio y casos de uso de los puertos; presenta los "
    "adaptadores de entrada y salida como dependencias externas.\n"
)
_BASELINE_LAYERED = (
    "ESTRUCTURA BASE SELECCIONADA: arquitectura en capas.\n"
    "Distingue presentacion, aplicacion, dominio e infraestructura y evita "
    "dependencias que salten capas.\n"
)
_BASELINE_CQRS = (
    "ESTRUCTURA BASE SELECCIONADA: CQRS (sujeta a las RESTRICCIONES DE \
VIABILIDAD).\n"
    "Separa el modelo de comandos (escritura) del de consultas (lectura): \
manejadores de comandos que validan y escriben, y manejadores de consultas que \
solo leen.\n"
    "Si el presupuesto, el equipo o el alcance son pequenos o no estan \
definidos, aplica la version MINIMA: una sola base de datos con modelos de \
lectura y escritura separados en el codigo (vistas o tablas de lectura), sin \
broker de eventos ni segunda base de datos; explica en 'Riesgo o costo' por que \
no se propone la version completa.\n"
    "Version completa (solo si volumen y equipo la justifican): almacen de \
lectura propio, sincronizado con eventos del lado de escritura.\n"
)
_BASELINE_EVENT_SOURCING = (
    "ESTRUCTURA BASE SELECCIONADA: event sourcing (sujeta a las RESTRICCIONES \
DE VIABILIDAD).\n"
    "El estado se deriva de un registro inmutable de eventos: almacen de \
eventos (solo agrega), agregados que emiten eventos y proyecciones que \
reconstruyen el estado de lectura.\n"
    "Con presupuesto o equipo pequenos, usa una tabla de eventos en la base de \
datos principal y proyecciones sencillas, sin broker ni almacen de eventos \
dedicado; explica en 'Riesgo o costo' el costo de versionar eventos y de \
reconstruir proyecciones.\n"
)
_BASELINE_CLEAN = (
    "ESTRUCTURA BASE SELECCIONADA: Clean Architecture.\n"
    "Distingue entidades de dominio, casos de uso, adaptadores de interfaz \
(controladores, repositorios) y frameworks/infraestructura; las dependencias \
apuntan siempre hacia adentro, hacia el dominio.\n"
)
_BASELINE_MODULAR_MONOLITH = (
    "ESTRUCTURA BASE SELECCIONADA: monolito modular.\n"
    "Un solo despliegue y una sola base de datos, dividido en modulos por \
dominio de negocio con fronteras claras: cada modulo expone una interfaz \
publica y no accede a las tablas de otro. No modeles servicios separados ni \
comunicacion por red entre modulos; si la evolucion a microservicios aplica, \
mencionala solo como evolucion futura en 'Riesgo o costo'.\n"
)
_BASELINE_SERVERLESS = (
    "ESTRUCTURA BASE SELECCIONADA: serverless (sujeta a las RESTRICCIONES DE \
VIABILIDAD).\n"
    "Funciones sin estado, una por responsabilidad, disparadas por HTTP, \
eventos o tareas programadas; el estado vive en servicios gestionados (base de \
datos, almacenamiento de objetos). Prefiere capas de uso gratuito y evita \
servidores propios; explica en 'Riesgo o costo' los limites de ejecucion y el \
arranque en frio.\n"
)
_BASELINE_API_GATEWAY_BFF = (
    "ESTRUCTURA BASE SELECCIONADA: API Gateway + Backend for Frontend \
(sujeta a las RESTRICCIONES DE VIABILIDAD).\n"
    "Un punto de entrada unico para los clientes y, si hay clientes con \
necesidades distintas (web, movil), un BFF por cliente que adapta y agrega las \
respuestas del backend.\n"
    "Con un solo cliente y un solo despliegue, expresa el BFF como una capa de \
API dentro del mismo proyecto, sin gateway ni servicios separados.\n"
)

# (fragmentos del nombre del patron ya normalizado, estructura base). Cubre los
# 10 patrones del catalogo; el orden solo importa si un nombre contiene dos.
_PATTERN_BASELINES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("microserv",), _BASELINE_MICROSERVICES),
    (("event sourcing", "event-sourcing"), _BASELINE_EVENT_SOURCING),
    (("event driven", "event-driven", "orientada a eventos"), _BASELINE_EVENT_DRIVEN),
    (("cqrs",), _BASELINE_CQRS),
    (("hexagonal", "ports and adapters", "puertos y adaptadores"), _BASELINE_HEXAGONAL),
    (("clean architecture", "arquitectura limpia"), _BASELINE_CLEAN),
    (("monolito modular", "modular monolith"), _BASELINE_MODULAR_MONOLITH),
    (("serverless", "function-as-a-service", "function as a service"), _BASELINE_SERVERLESS),
    (("api gateway", "backend for frontend", "bff"), _BASELINE_API_GATEWAY_BFF),
    (("capas", "layered"), _BASELINE_LAYERED),
)


def _architecture_baseline(
    *,
    citations: list[dict],
    project_name: str,
    description: str | None,
    requirements_text: str | None,
    prior_content: str | None,
    feedback: str | None = None,
) -> str:
    """Return the minimum structural shape for the inferred architecture.

    La estructura base sale del patron PRINCIPAL (el unico que el prompt
    declara como fuente principal), asi nunca contradice la regla de FUENTES Y
    REFERENCIAS: antes se elegia por palabras clave en descripcion,
    requerimientos y feedback, y un requerimiento como "a futuro podria migrar
    a microservicios" imponia esa base junto a "el unico patron principal es
    Monolito modular". El patron principal ya incorpora el feedback del
    usuario (ver ``_select_citations``). Los patrones secundarios son contexto
    y no imponen estructura. La base queda subordinada a las RESTRICCIONES DE
    VIABILIDAD (presupuesto, equipo, plazo).

    Solo si NO hay patron principal (sin RAG) se infiere por palabras clave
    del proyecto y del feedback, ignorando menciones negadas o hipoteticas.
    """
    primary_citation = next(
        (citation for citation in citations if citation.get("source_role") == "primary"),
        citations[0] if citations else None,
    )
    primary_name = (
        str(primary_citation.get("pattern_name") or "") if primary_citation else ""
    )

    if primary_name.strip():
        normalized_primary = _normalize_text(primary_name)
        for keys, baseline in _PATTERN_BASELINES:
            if any(key in normalized_primary for key in keys):
                return baseline
        # Patron fuera del catalogo: no se fuerza el de otro estilo.
        return (
            f"ESTRUCTURA BASE SELECCIONADA: la propia del patron principal "
            f"({primary_name.strip()}).\n"
            "Organiza Componentes y conexiones segun ese patron y no mezcles la "
            "estructura de otro estilo arquitectonico.\n"
        )

    # Sin patron principal. Con feedback la propuesta previa NO cuenta: si el
    # usuario pidio cambiar de arquitectura, el texto de la version anterior
    # (que sigue diciendo "microservicios", "CQRS"...) dejaria la base en el
    # estilo viejo.
    has_feedback = bool(feedback and feedback.strip())
    prior_context = "" if has_feedback else _strip_secondary_references(prior_content)
    normalized = _normalize_text(
        "\n".join(
            [
                project_name or "",
                description or "",
                requirements_text or "",
                feedback or "",
                prior_context,
            ]
        )
    )
    for keys, baseline in _PATTERN_BASELINES:
        if baseline is not _BASELINE_LAYERED and _keyword_wanted(keys, normalized):
            return baseline
    return _BASELINE_LAYERED


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
    """Compose the structured prompt that drives the LLM to produce 4 sections."""
    primary_citation = next(
        (citation for citation in citations if citation.get("source_role") == "primary"),
        citations[0] if citations else None,
    )
    secondary_citations = [citation for citation in citations if citation is not primary_citation]
    primary_pattern = (
        str(primary_citation.get("pattern_name") or "Patrón seleccionado")
        if primary_citation
        else None
    )
    secondary_patterns = [
        str(citation.get("pattern_name") or "Patrón sin nombre")
        for citation in secondary_citations
    ]
    if citations:
        context_blocks = []
        for index, cite in enumerate(citations, start=1):
            context_blocks.append(
                f"[{index}] {cite.get('pattern_name')}\n{cite.get('snippet') or ''}"
            )
        context_section = "\n\n".join(context_blocks)
        candidates_intro = (
            "Patrones recuperados de la base de conocimiento. El primero es el "
            "patron principal seleccionado; los restantes son solo contexto y no "
            "deben presentarse como citas:\n"
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
            "corresponda (Componentes, Tecnologias, Patrones y Justificación).\n"
            "- Si el usuario dice que quiere \"solo\" ciertas tecnologias, o pide "
            "reemplazar una por otra, ELIMINA las demas de ese aspecto; no las "
            "dejes junto a las nuevas.\n"
            "- No agregues tecnologias de ese aspecto que el usuario no nombro.\n"
            "- Si el usuario pide CAMBIAR el estilo o patron arquitectonico (por "
            "ejemplo de CQRS a capas), el patron nuevo pasa a ser el principal "
            "aunque los patrones candidatos digan otra cosa: reescribe Componentes, "
            "Patrones y Justificacion para el patron nuevo y ELIMINA los "
            "componentes que solo existian por el anterior (p. ej. el Read Model "
            "de CQRS). La regla de FUENTES Y REFERENCIAS no aplica a ese cambio.\n"
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

    source_rules = ""
    if primary_pattern:
        primary_suffix = (
            " (salvo que los CAMBIOS SOLICITADOS pidan otro patron).\n"
            if feedback and feedback.strip()
            else ".\n"
        )
        source_rules = (
            "\nFUENTES Y REFERENCIAS:\n"
            f"- El unico patron que puedes presentar como fuente principal es: {primary_pattern}"
            f"{primary_suffix}"
            "- En la seccion ## Patrones escribe exactamente una linea con el "
            "formato `- Patrón principal: <nombre>`.\n"
        )
        if secondary_patterns:
            source_rules += (
                "- Las referencias secundarias no son citas. Escribe una unica "
                "linea con el formato exacto `- Consultados no citados: "
                f"{', '.join(secondary_patterns)}`.\n"
            )

    architecture_baseline = _architecture_baseline(
        citations=citations,
        project_name=project_name,
        description=description,
        requirements_text=requirements_text,
        prior_content=prior_content,
        feedback=feedback,
    )

    viability_rules = (
        "RESTRICCIONES DE VIABILIDAD (obligatorias; tienen prioridad sobre la "
        "ESTRUCTURA BASE y sobre los patrones candidatos):\n"
        "- Extrae del resumen y de los documentos el presupuesto, el tamaño y "
        "capacidad del equipo, y el plazo de entrega. Trátalos como límites de "
        "diseño, no como notas informativas.\n"
        "- PROPORCIONALIDAD: dimensiona la solución al proyecto, no al patrón. "
        "Un proyecto sencillo (CRUD, pocos usuarios, MVP, prototipo o trabajo "
        "académico, equipo pequeño o presupuesto bajo) se resuelve con un solo "
        "despliegue, una sola base de datos y servicios gestionados o de capa "
        "gratuita. Cada pieza que agregue costo u operación (broker de "
        "mensajes, API Gateway propio, orquestador tipo Kubernetes, segunda "
        "base de datos, caché distribuida, service mesh, CQRS, event sourcing, "
        "observabilidad centralizada) SOLO se incluye si un requisito "
        "explícito la exige (volumen, disponibilidad, integración). Si no "
        "hay ese requisito, no la incluyas.\n"
        "- Mantén Componentes y Tecnologías al mínimo necesario (como "
        "referencia, entre 3 y 6 componentes en un proyecto sencillo; no "
        "más de 6) y prefiere tecnologías open source, conocidas por el "
        "equipo y de bajo costo de operación.\n"
        "- Tecnologías: como máximo 6 en un proyecto sencillo (lenguaje, "
        "framework, base de datos y solo lo que un requisito exija). NO listes "
        "como componente ni tecnología CI/CD, backups, servidor ASGI/WSGI, "
        "librería de hash, contenedores ni herramientas de despliegue salvo que "
        "un requisito los pida.\n"
        "- Patrones de complejidad alta (CQRS, event sourcing, orientada a "
        "eventos, microservicios) no son el patrón principal de un proyecto "
        "sencillo salvo que el usuario lo pida; usa capas o monolito modular.\n"
        "- No agregues capas que el framework ya trae (por ejemplo "
        "Repository/DAO sobre un ORM, un API Gateway propio dentro de un "
        "monolito, GraphQL además de REST). Para tareas programadas o "
        "recordatorios usa el planificador del framework o un cron; una cola "
        "con broker (Celery + Redis, RabbitMQ...) solo si un requisito exige "
        "reintentos, volumen alto o procesamiento pesado.\n"
        "- No inventes métricas (latencias, usuarios concurrentes, "
        "disponibilidad, SLAs) que no estén en los requerimientos.\n"
        "- Si el patrón principal recuperado es más pesado de lo que el "
        "proyecto necesita, preséntalo igualmente como principal pero aplícalo "
        "en su versión mínima viable. Lo que dejas fuera por costo o tamaño va "
        "en una línea de 'Riesgo o costo' como evolución futura, no en "
        "Componentes.\n"
        "- Con presupuesto, equipo o plazo sin definir, no inventes cifras. "
        "Asume presupuesto y equipo pequeños, declara la incertidumbre como "
        "riesgo o supuesto en la justificación y elige la opción más "
        "conservadora y viable.\n"
        "- Excepción: si el usuario pide expresamente una tecnología o "
        "componente (en los requerimientos o en los cambios solicitados), "
        "respétalo y señala su costo en 'Riesgo o costo'.\n"
        "- En la justificación del patrón principal explica explícitamente cómo "
        "la decisión respeta esos tres factores.\n"
    )

    coherence_rules = (
        "COHERENCIA (obligatoria): el patrón principal debe ser el que "
        "realmente describen los Componentes. Todo componente, servicio o "
        "gateway que nombres en 'Reflejo en la arquitectura' debe estar en "
        "la lista de Componentes; no menciones 'servicios internos' que no "
        "hayas listado. Si el proyecto es un solo despliegue, expresa el "
        "patrón principal en su versión mínima dentro de ese despliegue "
        "(por ejemplo, una capa de API dentro del mismo proyecto) y no como "
        "piezas de infraestructura separadas.\n"
    )

    return (
        "Eres un arquitecto de software. Tu tarea es redactar una propuesta de "
        "arquitectura para el proyecto indicado, en español, usando markdown.\n\n"
        f"Proyecto: {project_name}\n"
        f"{project_section}"
        f"{prior_section}"
        f"{feedback_section}"
        f"\n{viability_rules}"
        f"\n{architecture_baseline}"
        f"\n{coherence_rules}"
        "\nREGLA DE DECISION: tu trabajo es DECIDIR, no dejar la eleccion al "
        "usuario. Elige UNA sola opcion por aspecto (un estilo arquitectonico "
        "principal, una base de datos, un broker, un framework, etc.) y "
        "justificala en una linea con base en los requerimientos. NO ofrezcas "
        "alternativas ni uses formulas como \"X o Y\", \"X / Y\", \"X/Y\" (por "
        "ejemplo REST/GraphQL) o \"X (o Z)\"; "
        "no le pidas al usuario que elija. Si dudas, elige la opcion mas simple y barata que cumpla los requerimientos. "
        "El usuario podra pedir cambios despues con «Modificar».\n"
        "\nFormato OBLIGATORIO (responde exactamente con estas cuatro secciones, "
        "en este orden, con esos encabezados):\n\n"
        "## Componentes\n- ...\n\n"
        "## Tecnologias\n- ...\n\n"
        "## Patrones\n- ...\n\n"
        "## Justificación del patrón principal\n"
        "- Motivo de elección: explica por qué el patrón principal responde a "
        "los requisitos concretos del proyecto.\n"
        "- Reflejo en la arquitectura: relaciona el patrón con los componentes "
        "y conexiones que aparecerán en el diagrama.\n"
        "- Beneficio esperado: indica el beneficio técnico u operativo principal.\n"
        "- Riesgo o costo: explica una consecuencia o complejidad que debe "
        "gestionarse e indica, en una línea, qué se dejó fuera a propósito por "
        "presupuesto, equipo o plazo.\n\n"
        "Esta justificación debe hablar exclusivamente del patrón principal, "
        "no de las referencias 'Consultados no citados', y debe ser concreta: "
        "no uses frases genéricas como 'mejora la escalabilidad' sin vincularlas "
        "a componentes o requisitos de esta propuesta.\n\n"
        f"{candidates_intro}"
        f"{context_section}\n"
        f"{source_rules}"
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
    statement_timeout_ms: int | None = None,
    cancel_event: threading.Event | None = None,
) -> tuple[int, int, int]:
    """Insert proposal + interaction_log (+ approval for modify) atomically.

    ``statement_timeout_ms`` (F19): tope por sentencia solo para esta
    transaccion (``set_config(..., is_local=true)``); ``None`` = el de la BD.

    ``cancel_event`` (F19): lo marca el generador cuando el cliente cancela o se
    agota el tiempo mientras este hilo ya estaba guardando. Se comprueba justo
    antes del ``commit``; si esta marcado se hace rollback y se lanza
    ``_PersistCancelled``, asi no queda una iteracion huerfana. Es best-effort:
    si el ``commit`` ya empezo no hay forma de deshacerlo desde aqui.

    Returns ``(proposal_id, interaction_id, iteration)`` for the SSE done
    payload and the Engram mirror. The preconditions are checked again here to
    close the race between the router precheck and a delayed DB commit.
    """
    db = SessionLocal()
    try:
        if statement_timeout_ms is not None:
            db.execute(
                text("SELECT set_config('statement_timeout', :ms, true)"),
                {"ms": str(int(statement_timeout_ms))},
            )
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

        latest = (
            db.query(Proposal)
            .filter(Proposal.project_id == project_id)
            .order_by(Proposal.iteration.desc())
            .first()
        )
        if prior_proposal_id is not None:
            if latest is None or latest.id != prior_proposal_id:
                raise _ProposalDomainError(
                    "La propuesta ya no es la última iteración; recarga antes de modificar."
                )
            if int(iteration) != int(prior_iteration) + 1:
                raise _ProposalDomainError("La siguiente iteración no es válida; recarga e intenta de nuevo.")

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

        # Ultima comprobacion posible: despues del commit ya no hay vuelta atras.
        if cancel_event is not None and cancel_event.is_set():
            raise _PersistCancelled()

        db.commit()
        return proposal_id, interaction_id, int(iteration)
    except _PersistCancelled:
        db.rollback()
        logger.info(
            "Proposal save cancelled before commit project_id=%s iteration=%s",
            project_id,
            iteration,
        )
        raise
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
