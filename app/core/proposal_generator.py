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
import unicodedata
from time import perf_counter
from typing import Any, AsyncIterator

from langchain_core.documents import Document

from app.core.database import SessionLocal
from app.core.engram_client import EngramClient, EngramError
from app.core.llm_loader import build_langchain_model, LLMConfigError
from app.core.pattern_ranker import RERANK_POOL_SIZE, rank_candidates, ranking_log
from app.core.project_context import load_documents_text, load_requirements_text
from app.core.query_profile import (
    extract_project_profile,
    profile_to_constraints_text,
    profile_to_query,
)
from app.core.rag import similarity_search
from app.models import InteractionLog, Proposal, ProposalApproval, UserSession
from app.models.project import Project
from app.models.user import User

logger = logging.getLogger(__name__)

# En la fase de propuesta no hay umbral fijo de similitud (el piso de 0.85,
# RAG_MIN_SIMILARITY, vive solo en ``app/api/chat.py``). La
# consulta se arma con el nombre/descripcion/requerimientos del proyecto, asi
# que siempre esta dentro del dominio: en vez de descartar candidatos por un
# umbral fijo (que con multilingual-e5-small dejaba la lista vacia), se trae
# de la base los PROPOSAL_RAG_TOP_N patrones mas cercanos. El umbral sigue
# vigente en el chat, donde si hay preguntas fuera de tema.
#   PROPOSAL_RAG_TOP_N           patrones distintos que se citan (default 3)
#   PROPOSAL_RAG_CANDIDATE_CHUNKS chunks que se piden a PGVector antes de
#                                agrupar por patron (default 40)
#   PROPOSAL_RAG_MIN_SIMILARITY  piso opcional; 0.0 = sin piso (default)
PROPOSAL_RAG_TOP_N = int(os.getenv("PROPOSAL_RAG_TOP_N", "3"))
PROPOSAL_RAG_CANDIDATE_CHUNKS = int(os.getenv("PROPOSAL_RAG_CANDIDATE_CHUNKS", "40"))
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

        # 2c. El modelo se adquiere ANTES del RAG: ahora tambien sirve para
        # resumir el proyecto (perfil) y reordenar los candidatos.
        try:
            model = await asyncio.to_thread(build_langchain_model, self.user_id)
        except LLMConfigError as exc:
            yield ("error", str(exc))
            return

        # 3. Build summary query for RAG. Con perfil estructurado (dominio,
        # equipo, plazo, escala, atributos de calidad) la consulta se parece a
        # los chunks `scenarios`/`fit` del catalogo; sin perfil (LLM caido o
        # desactivado con PROPOSAL_QUERY_PROFILE=off) se usa la consulta
        # clasica: nombre + descripcion + feedback + requerimientos.
        classic_query = _build_summary_query(
            project.name,
            project.description,
            feedback,
            prior_content,
            requirements_text,
        )
        profile = await extract_project_profile(
            model,
            "\n".join(
                part
                for part in (
                    project.name,
                    project.description,
                    requirements_text,
                    documents_text,
                    feedback,
                )
                if part
            ),
        )
        summary_query = profile_to_query(profile, classic_query)
        if profile and feedback and feedback.strip():
            summary_query += f"\nCambios solicitados: {feedback.strip()}"
        logger.info(
            "Proposal RAG query project_id=%s profile=%s",
            effective_project_id,
            "ok" if profile else "fallback",
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
            for part in (
                project.name,
                project.description,
                requirements_text,
                feedback,
                # Cifras normalizadas (solo numeros y marcas fijas, nunca texto
                # libre del LLM) para que las reglas de escala tambien
                # funcionen cuando el usuario no escribio "equipo de 3 personas".
                profile_to_constraints_text(profile),
            )
            if part
        )
        # Dos pasadas: 1) el orden por similitud + reglas duras define un pool
        # de candidatos; 2) el LLM los reordena y ese orden desempata dentro de
        # las reglas duras (ver _select_citations).
        pool = _select_citations(
            docs,
            top_n=max(RERANK_POOL_SIZE, PROPOSAL_RAG_TOP_N),
            explicit_text=explicit_text,
            feedback=feedback,
        )
        ranked = await rank_candidates(model, summary_query, pool)
        if ranked:
            logger.info(
                "Proposal RAG rerank project_id=%s %s",
                effective_project_id,
                ranking_log(*ranked),
            )
        citations = _select_citations(
            docs,
            explicit_text=explicit_text,
            feedback=feedback,
            llm_ranking=ranked[0] if ranked else None,
            llm_reasons=ranked[1] if ranked else None,
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

        # 6. Stream LLM tokens + accumulate the full markdown.
        full_markdown_chunks: list[str] = []
        finish_reason: str | None = None
        try:
            async for event in model.astream(prompt):
                metadata = getattr(event, "response_metadata", None) or {}
                finish_reason = metadata.get("finish_reason") or finish_reason
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

        # Una propuesta cortada a la mitad (limite de tokens del modelo, stream
        # cerrado por el proveedor) NO se guarda: quedaria como iteracion vigente,
        # gastaria una de las PROPOSAL_MAX_ITER y la siguiente modificacion
        # partiria de un texto al que le faltan secciones.
        missing_sections = _missing_sections(full_markdown, source_count=len(citations))
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
                prompt=prompt,
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
PROPOSAL_COMPLEXITY_PENALTY = float(os.getenv("PROPOSAL_COMPLEXITY_PENALTY", "0.08"))
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
PROPOSAL_SMALL_TEAM_MAX = int(os.getenv("PROPOSAL_SMALL_TEAM_MAX", "4"))
PROPOSAL_SMALL_BUDGET_USD = float(os.getenv("PROPOSAL_SMALL_BUDGET_USD", "20000"))
PROPOSAL_SHORT_TIMELINE_MONTHS = int(os.getenv("PROPOSAL_SHORT_TIMELINE_MONTHS", "3"))

# "equipo de 4 personas" y tambien "equipo de 4" a secas ("MVP en 3 meses,
# equipo de 4, presupuesto bajo"). Sin sustantivo, la cifra no debe ir seguida
# de una unidad de tiempo/dinero ("equipo de 4 meses") ni de otro digito.
_TEAM_SIZE_RE = re.compile(
    r"equipo\s+(?:de\s+)?(\d+)(?!\d)"
    r"(?:\s*(?:ingenieros?|desarrolladores?|programadores?|personas|integrantes|"
    r"miembros|estudiantes|devs?|full-?stack)"
    r"|(?!\s*(?:mes|meses|semanas?|sprints?|dias?|horas?|anos?|usd|dolar|dolares|k\b|%)"
    r"|[.,]\d))"
)
_BUDGET_RE = re.compile(r"\$\s?(\d[\d.,]*)\s*(?:usd|dolares)?")
_TIMELINE_MONTHS_RE = re.compile(r"(\d+)\s*(?:mes|meses|month|months)\b")
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


def _tight_mvp_constraint(explicit_text: str | None) -> bool:
    """True para equipo pequeño con plazo corto: no admite distribución pesada.

    La señal debe contener ambas restricciones explícitas para no convertir un
    plazo corto de un equipo grande, o un equipo chico sin fecha, en una regla
    absoluta. MVP/prototipo no sustituye el plazo: ayuda al ranking general,
    pero esta prohibición requiere evidencia de equipo y tiempo.
    """
    if not explicit_text:
        return False
    normalized = _normalize_text(explicit_text)
    team_match = _TEAM_SIZE_RE.search(normalized)
    if not team_match or int(team_match.group(1)) > PROPOSAL_SMALL_TEAM_MAX:
        return False
    timelines = [int(match.group(1)) for match in _TIMELINE_MONTHS_RE.finditer(normalized)]
    return bool(timelines and min(timelines) <= PROPOSAL_SHORT_TIMELINE_MONTHS)


def _is_complex_distributed_pattern(pattern_name: str | None) -> bool:
    """Patrones que añaden operación distribuida incompatibles con un MVP ajustado."""
    name = _normalize_text(pattern_name)
    return any(
        marker in name
        for marker in (
            "microserv",
            "orientada a eventos",
            "event-driven",
            "service mesh",
            "saga",
        )
    )


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


# Una conjuncion seguida de una marca positiva abre una clausula nueva:
# "sin CQRS y con hexagonal" -> el "sin" ya no alcanza a hexagonal. Una
# conjuncion sola NO corta ("evitar microservicios y monolito" sigue negando
# ambos). El corte deja la conjuncion al inicio de la clausula ("y con ").
_POSITIVE_SWITCH = re.compile(
    r"\s(?=(?:y|e|pero)\s+(?:con|mejor|"
    r"us(?:a|ar|as|an|e|es|en|emos|ando)|utiliz\w+|prefier\w+|quier\w+|hag\w+)\b)"
)
# "... y con X": pide X aunque no haya un verbo ("con" solo cuenta tras el corte).
_SWITCH_WITH = re.compile(r"^\s*(?:y|e|pero)\s+con\s+" + _FILLER_WORDS + r"$")


def _clause_before(normalized_text: str, start: int) -> str:
    """Texto de la clausula que precede a ``start`` (max. 80 caracteres)."""
    window = normalized_text[max(0, start - 80) : start]
    clause = _CLAUSE_BREAK.split(window)[-1]
    return _POSITIVE_SWITCH.split(clause)[-1]


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
    if _WANT_CUE.search(clause) or _CHANGE_TO_CUE.search(clause) or _SWITCH_WITH.search(clause):
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


# "comparar monolito modular frente a microservicios": el usuario quiere VER la
# alternativa en la tabla, no cambiar el patron principal.
_COMPARE_CUE = re.compile(r"\b(?:compar\w*|frente\s+a|versus|vs)\b")


def _is_comparison_request(feedback: str | None) -> bool:
    """True si el feedback pide comparar patrones en vez de cambiar de patron."""
    return bool(feedback and _COMPARE_CUE.search(_normalize_text(feedback)))


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
    llm_ranking: list[str] | None = None,
    llm_reasons: dict[str, str] | None = None,
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

    ``llm_ranking`` (nombres de patron, del mejor al peor; ver
    app/core/pattern_ranker.py) reemplaza a la similitud como DESEMPATE: se
    aplica despues de las reglas duras (descalificacion por escala, rechazo o
    pedido del usuario, senal "no usar"), asi que el LLM nunca puede saltarse
    una prohibicion. Los patrones que no aparecen en la lista quedan detras.

    ``feedback`` (los cambios que pide el usuario al modificar) MANDA sobre el
    ranking: el patron que el feedback pide pasa a ser el principal aunque tenga
    menos similitud, mas complejidad o la regla dura de escala (equipo<=4 y
    plazo<=3 meses) lo descartaria, y el que el feedback quita ("sin CQRS",
    "cambia CQRS por X") no se cita. Si el feedback solo pide COMPARAR ("comparar
    monolito modular frente a microservicios") el patron nombrado se cita siempre
    (tiene fila en la tabla) pero no pasa a principal. ``explicit_text``
    (requerimientos) solo evita la penalizacion por complejidad; un patron de
    escala descartada que el usuario pidio ahi tambien se cita, marcado
    ``scale_disqualified``, para que la tabla lo muestre como alternativa
    descartada con su razon.
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
    if _is_comparison_request(feedback):
        # Pedir una comparacion no es pedir el cambio de patron principal. Una
        # mencion sin verbo ("comparar X frente a Y") es ambigua (None) para
        # _feedback_stance, pero aqui si debe tener fila en la tabla.
        normalized_feedback = _normalize_text(feedback)
        stance = {
            key: (
                "compare"
                if value == "want"
                or (
                    value is None
                    and _alias_mentions(
                        str(best_fit[key].metadata.get("pattern_name") or ""),
                        normalized_feedback,
                    )
                )
                else value
            )
            for key, value in stance.items()
        }

    # Descalificacion dura por escala del proyecto (ver comentario junto a
    # PROPOSAL_SMALL_TEAM_MAX): un patron "alta" complejidad no puede ser
    # principal en un proyecto chico salvo que el usuario lo pida por nombre
    # (stance == "want") o lo mencione explicitamente en sus requerimientos.
    small_scale = _small_scale_signal(explicit_text)
    tight_mvp = _tight_mvp_constraint(explicit_text)

    def _scale_disqualified(key: Any) -> bool:
        # Esta es una prohibición, no una preferencia: con menos de cinco
        # personas y <= 3 meses, microservicios/eventos distribuidos desvían
        # capacidad de entrega hacia DevOps, depuración y consistencia.
        # Solo la cambia un feedback que PIDE el patron ("cambia a
        # microservicios"): el feedback manda sobre los requerimientos y el
        # prompt obliga a declarar su costo en "Riesgo o costo".
        if stance[key] == "want":
            return False
        if tight_mvp and _is_complex_distributed_pattern(
            best_fit[key].metadata.get("pattern_name")
        ):
            return True
        if not small_scale:
            return False
        doc = best_fit[key]
        if _COMPLEXITY_LEVEL.get(doc.metadata.get("complexity"), 0) < 2:
            return False
        return not _explicitly_requested(doc.metadata.get("pattern_name"), explicit_text)

    llm_position = {_normalize_text(name): i for i, name in enumerate(llm_ranking or [])}

    def _llm_position(doc: Document) -> int:
        if not llm_position:
            return 0  # sin ranking del LLM no cambia nada
        return llm_position.get(
            _normalize_text(doc.metadata.get("pattern_name")), len(llm_position)
        )

    ordered = sorted(
        best_fit.items(),
        key=lambda item: (
            _scale_disqualified(item[0]),
            stance[item[0]] == "reject",
            stance[item[0]] != "want",
            _avoided(item[0]),
            _llm_position(item[1]),
            -_score(item[1]),
        ),
    )

    def _eligible(key: Any, doc: Document) -> bool:
        if stance[key] == "reject":
            return False
        # Lo que el usuario pidio por nombre se cita aunque no llegue al piso.
        return stance[key] in ("want", "compare") or _sim(doc) >= floor

    def _pinned(key: Any, doc: Document) -> bool:
        # Se citan siempre (tienen fila en la tabla de trade-offs): lo que el
        # feedback pide o compara, y lo que el usuario pidio en sus
        # requerimientos pero la regla de escala descarta (alternativa
        # descartada con su razon). Sin esto, con 19 patrones en la base nunca
        # llegarian al top_n y la tabla no podria mostrarlos.
        if stance[key] in ("want", "compare"):
            return True
        return _scale_disqualified(key) and _explicitly_requested(
            doc.metadata.get("pattern_name"), explicit_text
        )

    order_index = {key: position for position, (key, _doc) in enumerate(ordered)}
    eligible = [(key, doc) for key, doc in ordered if _eligible(key, doc)]
    chosen = eligible[:limit]
    for key, doc in eligible[limit:]:
        if not _pinned(key, doc):
            continue
        slot = next(
            (i for i in range(len(chosen) - 1, -1, -1) if not _pinned(*chosen[i])),
            None,
        )
        if slot is None:
            continue
        chosen[slot] = (key, doc)
    chosen.sort(key=lambda item: order_index[item[0]])

    citations: list[dict] = []
    for _key, doc in chosen:
        citations.append(
            {
                "pattern_id": doc.metadata.get("pattern_id"),
                "pattern_name": doc.metadata.get("pattern_name"),
                "similarity": doc.metadata.get("similarity"),
                "snippet": (doc.page_content or "")[:240],
                "tradeoffs": doc.metadata.get("tradeoffs") or {},
            }
        )
        # Solo si NO es el principal: un patron descartado por escala que aun
        # asi queda primero (unico candidato) no puede presentarse "descartado".
        if len(citations) > 1 and _scale_disqualified(_key):
            citations[-1]["scale_disqualified"] = True
        reason = (llm_reasons or {}).get(str(doc.metadata.get("pattern_name")))
        if reason:
            citations[-1]["llm_reason"] = reason
    # La primera coincidencia es la que el motor selecciona como sustento
    # principal de la propuesta. El resto aporta contexto, pero no se debe
    # presentar como si estuviera citado: esa distinción llega hasta la UI.
    for index, citation in enumerate(citations):
        citation["source_role"] = (
            "primary" if index == 0 else "tradeoff_option"
        )

    return citations


# El modelo a veces numera o pone en negrita el encabezado ("## 5. Trade-offs y
# decisión", "## **Trade-offs y decisión**"): se tolera esa decoracion antes del
# texto. Se compara sobre texto normalizado (sin acentos, en minusculas).
_HEADING_DECOR = r"[*_`\d.)\s]*"
_TRADEOFF_HEADING_TEXT = r"trade[\s-]?offs?\s*(?:y|&)\s*decision\w*"

_REQUIRED_HEADINGS = (
    ("Componentes", r"componentes?\b"),
    ("Tecnologias", r"tecnologias?\b"),
    ("Patrones", r"patr(?:on|ones)\b"),
    (
        "Justificación del patrón principal",
        r"justificacion(?:\s+del\s+patron(?:\s+principal)?)?\b",
    ),
    ("Trade-offs y decisión", _TRADEOFF_HEADING_TEXT),
)
# "Riesgo o costo" con las variantes que escribe un modelo ("Riesgos y costos",
# "Riesgo/costo", "Riesgo y costo"), o un bullet solo "Riesgo:" / "Costo:".
_RISK_OR_COST_RE = re.compile(
    r"riesgos?\s*(?:o|y|e|/|,|-)\s*costos?|^\W*(?:riesgos?|costos?)\s*:",
    re.MULTILINE,
)


# Minimo auditable de la decision (criterio de aceptacion F10): 3 opciones por
# tabla y 3 criterios de comparacion (ventajas, desventajas, complejidad/costo).
MIN_TRADEOFF_OPTIONS = 3
NO_RAG_SOURCE_LABEL = "Sin fuente RAG"

_HEADING_LEVEL_RE = re.compile(r"^\s*(#{1,6})\s")
_TRADEOFF_HEADING_RE = re.compile(
    r"^\s*(#{1,6})\s+" + _HEADING_DECOR + _TRADEOFF_HEADING_TEXT
)
# Misma definicion de separador que usa el render del frontend (markdown.tsx):
# si la tabla no cumple esto, la UI tampoco la dibuja como tabla.
_TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$")
_LIST_ITEM_RE = re.compile(r"^\s*([-*+]|\d+\.)\s")
_CITATION_RE = re.compile(r"\[(\d+)\]")


def _missing_sections(markdown: str | None, source_count: int = 0) -> list[str]:
    """Secciones obligatorias que faltan en la propuesta (lista vacia = completa).

    Comprueba los cinco encabezados ``##`` del formato (tolerando singular/
    plural, acentos, negritas y numeracion) y que la justificacion llegue hasta
    su ultimo punto (riesgo o costo), que es lo primero que se pierde cuando la
    respuesta se corta. El riesgo se busca solo DESPUES del encabezado de la
    justificacion y ANTES del de trade-offs, para no confundirlo con otra
    mencion de la propuesta. ``source_count`` es el numero de patrones RAG que
    se le dieron al modelo: con fuentes, la tabla de trade-offs debe citarlas
    como ``[n]``.
    """
    normalized = _normalize_text(markdown)
    missing: list[str] = []
    justification_start: int | None = None
    for label, pattern in _REQUIRED_HEADINGS:
        match = re.search(
            r"^[ \t]*#{1,6}[ \t]*" + _HEADING_DECOR + pattern,
            normalized,
            re.MULTILINE,
        )
        if match is None:
            missing.append(label)
        elif label == "Justificación del patrón principal":
            justification_start = match.end()
    if justification_start is not None:
        tradeoff_heading = re.compile(
            r"^[ \t]*#{1,6}[ \t]*" + _HEADING_DECOR + _TRADEOFF_HEADING_TEXT,
            re.MULTILINE,
        ).search(normalized, justification_start)
        justification_end = (
            tradeoff_heading.start() if tradeoff_heading else len(normalized)
        )
        if not _RISK_OR_COST_RE.search(
            normalized, justification_start, justification_end
        ):
            missing.append("Riesgo o costo")
    if "Trade-offs y decisión" not in missing:
        if not _has_tradeoff_comparison(markdown, source_count):
            missing.append("Tabla de trade-offs (3 opciones y 3 criterios)")
        elif not _has_decision_point(markdown):
            missing.append("Recomendación y punto de decisión")
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


def _tradeoff_section(markdown: str | None) -> list[str] | None:
    """Lineas de ``## Trade-offs y decisión`` hasta el siguiente encabezado del mismo nivel o superior."""
    if not markdown:
        return None
    lines = markdown.splitlines()
    start = level = None
    for index, line in enumerate(lines):
        match = _TRADEOFF_HEADING_RE.match(_normalize_text(line))
        if match:
            start, level = index, len(match.group(1))
            break
    if start is None:
        return None
    section: list[str] = []
    for line in lines[start + 1 :]:
        heading = _HEADING_LEVEL_RE.match(line)
        if heading and len(heading.group(1)) <= level:
            break
        section.append(line)
    return section


def _table_cells(line: str) -> list[str]:
    """Celdas de una fila markdown; un ``\\|`` escapado es texto, no separador."""
    text = line.strip()
    if text.startswith("|"):
        text = text[1:]
    if text.endswith("|") and not text.endswith("\\|"):
        text = text[:-1]
    return [cell.replace("\\|", "|").strip() for cell in re.split(r"(?<!\\)\|", text)]


def _criterion_for_header(header: str) -> str | None:
    """Criterio de comparacion que representa una cabecera, tolerando formato.

    Acepta ``**Ventajas**``, ``Complejidad / costo``, ``Complejidad y costo``,
    ``Costo`` etc. Las columnas de apoyo (Opción, Ajuste, Fuente RAG) devuelven None.
    """
    text = re.sub(r"[*_`]", "", _normalize_text(header)).strip()
    if text.startswith("desventaja"):
        return "desventajas"
    if text.startswith("ventaja"):
        return "ventajas"
    if "complejidad" in text or "costo" in text:
        return "complejidad_costo"
    return None


def _has_tradeoff_comparison(markdown: str | None, source_count: int = 0) -> bool:
    """Verifica el mínimo auditable: 3 alternativas y 3 criterios comparables.

    Comprobacion estructural (no juzga la calidad del texto del modelo):
      * hay una tabla markdown valida (cabecera + separador) dentro de la seccion;
      * trae las columnas Ventajas, Desventajas y Complejidad/costo;
      * al menos 3 filas con la opcion y los tres criterios rellenos (las filas
        vacias o las lineas de texto con ``|`` que siguen a la tabla no cuentan);
      * si hubo fuentes RAG, al menos ``min(source_count, 3)`` filas con un
        ``[n]`` existente y DISTINTO (tres filas que citen todas ``[1]`` no
        cuentan). El prompt pide una fila por cada fuente recuperada, pero la
        validacion solo exige ese minimo: con ``PROPOSAL_RAG_TOP_N=3`` ambas
        cosas coinciden. Se lee primero la columna Fuente RAG y, si no trae un
        ``[n]`` valido, el resto de la fila.
    """
    section = _tradeoff_section(markdown)
    if section is None:
        return False

    table = None
    for index in range(len(section) - 1):
        if "|" in section[index] and _TABLE_SEPARATOR_RE.match(section[index + 1]):
            rows: list[list[str]] = []
            for line in section[index + 2 :]:
                if not line.strip() or "|" not in line or _LIST_ITEM_RE.match(line):
                    break
                rows.append(_table_cells(line))
            table = (_table_cells(section[index]), rows)
            break
    if table is None:
        return False

    headers, rows = table
    columns: dict[str, int] = {}
    for position, header in enumerate(headers):
        criterion = _criterion_for_header(header)
        if criterion and criterion not in columns:
            columns[criterion] = position
    if len(columns) < 3:
        return False

    def _cell(row: list[str], position: int) -> str:
        value = row[position] if position < len(row) else ""
        return value.strip(" -–—:")

    complete_rows = [
        row
        for row in rows
        if _cell(row, 0) and all(_cell(row, position) for position in columns.values())
    ]
    if len(complete_rows) < MIN_TRADEOFF_OPTIONS:
        return False

    if source_count > 0:
        source_position = next(
            (
                position
                for position, header in enumerate(headers)
                if re.sub(r"[*_`]", "", _normalize_text(header)).strip().startswith("fuente")
            ),
            None,
        )

        def _first_valid_citation(row: list[str]) -> int | None:
            candidates = []
            if source_position is not None and source_position < len(row):
                candidates.append(row[source_position])
            candidates.append(" ".join(row))
            for text in candidates:
                for number in _CITATION_RE.findall(text):
                    if 1 <= int(number) <= source_count:
                        return int(number)
            return None

        cited = {
            number
            for number in map(_first_valid_citation, complete_rows)
            if number is not None
        }
        if len(cited) < min(source_count, MIN_TRADEOFF_OPTIONS):
            return False
    return True


def _has_decision_point(markdown: str | None) -> bool:
    """La seccion debe cerrar con ``Recomendación:`` y ``Punto de decisión``."""
    text = _normalize_text("\n".join(_tradeoff_section(markdown) or []))
    return bool(
        re.search(r"^\s*[-*+]?\s*[*_]*recomendacion[*_]*\s*:", text, re.MULTILINE)
        and "punto de decision" in text
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

_BASELINE_ETL_ELT = (
    "ESTRUCTURA BASE SELECCIONADA: pipeline de datos ETL/ELT por lotes.\n"
    "Distingue fuentes, extraccion, transformacion y carga (o carga y luego "
    "transformacion dentro del almacen analitico) y el consumo analitico "
    "(reportes, dashboards). Muestra la orquestacion de las tareas y la "
    "validacion de calidad de datos como componentes explicitos; prefiere "
    "procesos por lotes simples antes que streaming.\n"
)
_BASELINE_LAMBDA_KAPPA = (
    "ESTRUCTURA BASE SELECCIONADA: arquitectura Lambda/Kappa (sujeta a las "
    "RESTRICCIONES DE VIABILIDAD).\n"
    "Si el equipo o el presupuesto son pequenos, aplica un unico camino de "
    "procesamiento (Kappa) y explica en 'Riesgo o costo' por que no se "
    "mantienen dos caminos. Distingue ingestion, procesamiento (batch y/o "
    "streaming), almacenamiento de servicio y consumo.\n"
)
_BASELINE_MEDALLION = (
    "ESTRUCTURA BASE SELECCIONADA: lakehouse con capas Medallion.\n"
    "Distingue la capa bronce (datos crudos), plata (limpios y conformados) y "
    "oro (listos para consumo analitico), con las transformaciones entre "
    "capas y los consumidores (BI, ciencia de datos) como dependencias "
    "explicitas.\n"
)
_BASELINE_MICROKERNEL = (
    "ESTRUCTURA BASE SELECCIONADA: microkernel (arquitectura de plugins).\n"
    "Un nucleo minimo con las reglas comunes y un contrato estable de "
    "extension; cada plugin es un componente independiente que solo depende "
    "de ese contrato, no de otros plugins.\n"
)
_BASELINE_MLOPS = (
    "ESTRUCTURA BASE SELECCIONADA: pipeline de MLOps (sujeta a las "
    "RESTRICCIONES DE VIABILIDAD).\n"
    "Distingue preparacion de datos, entrenamiento, registro y versionado de "
    "modelos, serving (API o por lotes) y monitoreo. Con equipo o presupuesto "
    "pequenos, automatiza solo lo imprescindible y explica en 'Riesgo o "
    "costo' que se dejo manual.\n"
)
_BASELINE_MVC_MVVM = (
    "ESTRUCTURA BASE SELECCIONADA: MVC/MVVM.\n"
    "Separa el modelo (datos y reglas), la vista (pantallas) y el "
    "controlador o viewmodel que media entre ambos; la vista no accede "
    "directamente al almacenamiento.\n"
)
_BASELINE_PIPES_FILTERS = (
    "ESTRUCTURA BASE SELECCIONADA: pipes and filters.\n"
    "Filtros independientes y sin estado compartido, cada uno con una unica "
    "transformacion, conectados por tuberias en un orden explicito; muestra "
    "la entrada y la salida de cada etapa.\n"
)
_BASELINE_SAGA = (
    "ESTRUCTURA BASE SELECCIONADA: saga (sujeta a las RESTRICCIONES DE "
    "VIABILIDAD).\n"
    "Solo si hay transacciones que cruzan varios servicios: pasos locales "
    "coordinados por orquestacion o coreografia, cada uno con su accion de "
    "compensacion. Con un unico despliegue y una base de datos, usa una "
    "transaccion local y explica en 'Riesgo o costo' por que no se necesita "
    "saga.\n"
)
_BASELINE_SOA = (
    "ESTRUCTURA BASE SELECCIONADA: arquitectura orientada a servicios (SOA).\n"
    "Servicios de negocio reutilizables con contratos explicitos, expuestos "
    "mediante una capa de integracion (bus o API) que gestiona el enrutamiento "
    "y la orquestacion entre ellos.\n"
)

# (fragmentos del nombre del patron ya normalizado, estructura base). Cubre los
# 19 patrones del catalogo; el orden solo importa si un nombre contiene dos
# ("Data Lakehouse con capas Medallion" contiene "capas": va antes que capas).
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
    (("etl / elt", "etl"), _BASELINE_ETL_ELT),
    (("lambda / kappa", "lambda", "kappa"), _BASELINE_LAMBDA_KAPPA),
    (("medallion", "lakehouse"), _BASELINE_MEDALLION),
    (("microkernel",), _BASELINE_MICROKERNEL),
    (("mlops",), _BASELINE_MLOPS),
    (("mvc", "mvvm"), _BASELINE_MVC_MVVM),
    (("pipes and filters", "tuberias y filtros"), _BASELINE_PIPES_FILTERS),
    (("saga",), _BASELINE_SAGA),
    (("orientada a servicios", "soa"), _BASELINE_SOA),
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
    """Compose the structured prompt that drives the LLM to produce the 5 sections."""
    primary_citation = next(
        (citation for citation in citations if citation.get("source_role") == "primary"),
        citations[0] if citations else None,
    )
    primary_pattern = (
        str(primary_citation.get("pattern_name") or "Patrón seleccionado")
        if primary_citation
        else None
    )

    # La tabla de trade-offs exige >=3 opciones. Con menos de 3 patrones
    # recuperados (p. ej. tras un rechazo por feedback) el modelo completa con
    # alternativas marcadas "Sin fuente RAG" en vez de inventar un [n]; asi las
    # reglas de filas nunca se contradicen con el minimo de 3.
    source_count = len(citations)
    if source_count >= MIN_TRADEOFF_OPTIONS:
        table_rows_rule = (
            "- Usa únicamente los patrones [n] recuperados de la base como filas de "
            "la tabla; los nombres de ejemplos del usuario no son un catálogo fijo. "
            "Incluye una fila por cada fuente recuperada, aunque se descarte.\n"
        )
        table_rows_instruction = (
            "Incluye una fila por CADA alternativa [n] recuperada (al menos tres "
            "filas). Para cada una cita su fuente como [n], desarrolla sus "
            "ventajas en dos efectos técnicos tangibles y fundamenta ventajas y "
            "desventajas solo en los trade-offs recibidos de RAG. "
        )
        template_source = "[1]"
    elif source_count > 0:
        table_rows_rule = (
            "- Usa como filas de la tabla los patrones [n] recuperados de la base "
            "(una fila por cada fuente, aunque se descarte) y completa hasta al "
            f"menos tres filas con alternativas marcadas `{NO_RAG_SOURCE_LABEL}`; "
            "los nombres de ejemplos del usuario no son un catálogo fijo.\n"
        )
        table_rows_instruction = (
            f"Solo se recuperaron {source_count} patrón(es) de la base. Incluye "
            "una fila por CADA [n] recuperado, con su fuente como [n] y ventajas "
            "y desventajas fundamentadas solo en los trade-offs recibidos de RAG, "
            "y completa hasta al menos tres filas con alternativas razonables "
            "para este proyecto cuya columna Fuente RAG diga exactamente "
            f"`{NO_RAG_SOURCE_LABEL}` (nunca un [n] que no exista; sus ventajas y "
            "desventajas son criterio general del modelo, no evidencia de la "
            "base, y debes indicarlo). "
        )
        template_source = "[1]"
    else:
        table_rows_rule = (
            "- No hay patrones recuperados: las filas de la tabla son alternativas "
            "razonables para este proyecto, todas marcadas "
            f"`{NO_RAG_SOURCE_LABEL}`.\n"
        )
        table_rows_instruction = (
            "No hay fuentes recuperadas: incluye al menos tres filas con "
            "alternativas razonables para este proyecto y escribe exactamente "
            f"`{NO_RAG_SOURCE_LABEL}` en la columna Fuente RAG de cada una, sin "
            "números entre corchetes. Sus ventajas y desventajas son criterio "
            "general del modelo, no evidencia de la base. "
        )
        template_source = NO_RAG_SOURCE_LABEL

    if citations:
        context_blocks = []
        for index, cite in enumerate(citations, start=1):
            tradeoffs = cite.get("tradeoffs") or {}
            tradeoffs_context = (
                json.dumps(tradeoffs, ensure_ascii=False)
                if tradeoffs
                else "Sin trade-offs estructurados para este patrón."
            )
            context_blocks.append(
                f"[{index}] {cite.get('pattern_name')}\n"
                f"Contexto: {cite.get('snippet') or ''}\n"
                f"Trade-offs RAG: {tradeoffs_context}"
                + (
                    "\nDescartado por la escala del proyecto (equipo, plazo o "
                    "presupuesto): preséntalo en la tabla solo como alternativa "
                    "descartada y explica la razón; no lo recomiendes."
                    if cite.get("scale_disqualified")
                    else ""
                )
                + (
                    f"\nAjuste al proyecto (análisis previo): {cite['llm_reason']}"
                    if cite.get("llm_reason")
                    else ""
                )
            )
        context_section = "\n\n".join(context_blocks)
        candidates_intro = (
            "Patrones recuperados de la base de conocimiento. Cada [n] es una "
            "opción real disponible en la base y una fuente válida SOLO para la "
            "comparación de trade-offs; no agregues opciones de ejemplos genéricos "
            "que no aparezcan aquí"
            + (
                ""
                if source_count >= MIN_TRADEOFF_OPTIONS
                else f" (salvo filas de relleno marcadas `{NO_RAG_SOURCE_LABEL}` "
                "hasta llegar a tres)"
            )
            + ":\n"
        )
    else:
        context_section = "No se recuperaron patrones de la base de conocimiento."
        # Sin contexto NO se pide citar con [n]: el modelo se inventaba
        # referencias [1]..[6] que no existian.
        candidates_intro = (
            "No hay patrones recuperados de la base de conocimiento. Declara que "
            "no se puede elaborar una comparación RAG verificable y NO uses "
            "números entre corchetes ni inventes opciones atribuidas a la base.\n"
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
            "corresponda (Componentes, Tecnologias, Patrones, Justificación y "
            "Trade-offs y decisión: la tabla y la Recomendación deben reflejar "
            "el cambio).\n"
            "- Si el usuario dice que quiere \"solo\" ciertas tecnologias, o pide "
            "reemplazar una por otra, ELIMINA las demas de ese aspecto; no las "
            "dejes junto a las nuevas.\n"
            "- No agregues tecnologias de ese aspecto que el usuario no nombro.\n"
            "- Si el usuario pide CAMBIAR el estilo o patron arquitectonico (por "
            "ejemplo de CQRS a capas), el patron nuevo pasa a ser el principal "
            "aunque los patrones candidatos digan otra cosa: reescribe Componentes, "
            "Patrones, Justificacion y la Recomendacion de Trade-offs para el "
            "patron nuevo y ELIMINA los "
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
        if source_count >= MIN_TRADEOFF_OPTIONS:
            source_rules += (
                "- En `## Trade-offs y decisión` incluye exactamente una fila por "
                "cada patrón [n] recuperado arriba. No reemplaces esas filas por "
                "ejemplos fijos ni añadas un patrón que no tenga fuente [n].\n"
            )
        else:
            source_rules += (
                "- En `## Trade-offs y decisión` incluye una fila por cada patrón "
                "[n] recuperado arriba y completa hasta tres filas con "
                f"alternativas marcadas `{NO_RAG_SOURCE_LABEL}`. No reemplaces las "
                "filas con fuente por ejemplos fijos.\n"
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
        "\nREGLAS DE TRADE-OFFS REALES (obligatorias):\n"
        "- Equipo, plazo y presupuesto son criterios de primera clase en la tabla "
        "y en la recomendación; no uses escenarios ideales de empresas grandes. "
        "Explica cómo la opción recomendada reduce el riesgo de entrega en el "
        "plazo real y conserva seguridad y disponibilidad base.\n"
        "- Si los requisitos indican equipo de hasta 4 personas Y plazo de hasta "
        "3 meses, queda PROHIBIDO recomendar microservicios, service mesh, "
        "múltiples bases por servicio, Saga o arquitectura distribuida orientada "
        "a eventos. Recomienda monolito modular o una arquitectura limpia/hexagonal "
        "en un despliegue y una base de datos. Las opciones prohibidas solo pueden "
        "aparecer como alternativas descartadas, con la razón explícita. "
        "Excepción: si el feedback del usuario pide expresamente cambiar a uno de "
        "esos patrones, respétalo, preséntalo como principal y declara su costo en "
        "'Riesgo o costo'; si solo piden compararlo, mantén tu recomendación y deja "
        "ese patrón como alternativa descartada con su razón.\n"
        "- En cada fila de Trade-offs sustituye la frase genérica 'mayor "
        "complejidad' por fricciones operativas concretas: tiempo y dificultad "
        "de debugging local, curva de aprendizaje DevOps, riesgo de consistencia "
        "de datos y sobrecarga de mantenimiento. No inventes horas, porcentajes o "
        "SLAs si los requisitos no los proporcionan.\n"
        f"{table_rows_rule}"
        "- Ventajas NO puede contener adjetivos aislados como 'simple', 'flexible' "
        "o 'escalable'. Para cada patrón, transforma el trade-off de RAG en al "
        "menos dos efectos técnicos concretos: mecanismo (por ejemplo límites de "
        "módulo, transacción, aislamiento, despliegue o escalado) + impacto en "
        "el trabajo del equipo o un requisito del proyecto.\n"
        "- Desventajas debe conservar la evidencia RAG y detallar la fricción "
        "operativa que causa en ESTE proyecto. Si aplica, vincula debugging local, "
        "operación/DevOps, consistencia de datos y mantenimiento; no los copies "
        "indiscriminadamente a patrones donde no correspondan.\n"
        "\nREGLA DE DECISION: primero compara alternativas de forma explícita y "
        "después recomienda UNA sola opción. No dejes elecciones implícitas ni "
        "uses fórmulas ambiguas como \"X o Y\" o \"REST/GraphQL\" fuera de "
        "la tabla. Si dudas, recomienda la opcion mas simple y barata que cumpla "
        "los requisitos. "
        "El usuario podrá pedir alternativas o cambios después.\n"
        "\nFormato OBLIGATORIO (responde exactamente con estas cinco secciones, "
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
        "## Trade-offs y decisión\n"
        "Incluye UNA tabla Markdown con tres o más opciones (una por fila) y, "
        "como mínimo, las columnas Ventajas, Desventajas y Complejidad/costo. "
        "Añade Ajuste a requisitos y Fuente RAG para que la decisión sea auditable:\n"
        "| Opción | Ventajas | Desventajas | Complejidad/costo | Ajuste a requisitos | Fuente RAG |\n"
        "| --- | --- | --- | --- | --- | --- |\n"
        f"| ... | ... | ... | ... | ... | {template_source} |\n"
        f"{table_rows_instruction}"
        "Tras la tabla añade exactamente: "
        "`- Recomendación: <una opción>` y `- Punto de decisión: ¿Aprueba los "
        "trade-offs?`. No inventes una cita cuando no haya fuente RAG.\n\n"
        "Esta justificación debe hablar exclusivamente del patrón principal, "
        "no de las demás alternativas de la tabla de trade-offs, y debe ser concreta: "
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
    prompt: str,
) -> tuple[int, int, int]:
    """Insert proposal + interaction_log (+ approval for modify) atomically.

    ``prompt`` es el texto EXACTO que se envio al modelo (con descripcion,
    requerimientos y documentos del proyecto): el log de auditoria debe poder
    explicar la respuesta que produjo, y reconstruirlo sin esos campos lo
    dejaba sin los datos que mas la moldean.

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
            prompt=prompt[:65000],
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
