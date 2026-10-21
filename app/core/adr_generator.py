"""ADR del proyecto: documento final de la fase Revisión.

Reúne en un solo Architecture Decision Record todo lo que se decidió en las
fases anteriores, para que quien lo lea pueda empezar a construir el sistema:

* Lo que viene de los datos (siempre está, no depende del LLM): contexto,
  requerimientos, propuesta aprobada (con su tabla de trade-offs), diagrama
  aprobado (Mermaid), referencias con fuentes curadas, historial de decisiones
  y anexo con la elicitación.
* Lo que redacta el LLM a partir de esos datos: componentes, stack,
  consecuencias, riesgos, plan de implementación, primer sprint, estructura
  del repositorio y preguntas abiertas. Si el LLM falla (rate limit, timeout,
  respuesta vacía), el ADR se genera igual, sin esas secciones y con un aviso.

La recolección (``collect_adr_context``) toca la base de datos; el armado
(``render_adr_markdown``) es puro para poder testearlo sin DB ni LLM.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy.orm import Session

from app.core.domain_concerns import (
    DomainConcern,
    concern_by_question,
    concern_mentioned,
    uncovered_concerns,
)
from app.core.env import env_float, env_int
from app.core.llm_errors import (
    INCOMPLETE,
    TOO_LARGE,
    classify_llm_error,
    estimate_tokens,
    llm_error_message,
)
from app.core.mermaid_validator import extract_mermaid_block, sanitize_mermaid
from app.core.session_store import latest_diagram_decisions
from app.core.text_norm import normalize_text
from app.core.viability_rules import (
    ASSUMPTION_MARK,
    COMMON_VIABILITY_RULES,
    GUIDE_ASSUMPTION_RULES,
)
from app.models.approval import Approval
from app.models.message import Message
from app.models.project import Project
from app.models.proposal import Proposal
from app.models.session import UserSession

_LOGGER = logging.getLogger(__name__)

ELICITATION_PHASE = "requerimientos"
DIAGRAM_PHASE = "diagram"
# Clave dentro de engram_state[project_id] donde se guarda el ADR generado.
ADR_STATE_KEY = "adr"

ADR_LLM_TIMEOUT_S = env_float("ADR_LLM_TIMEOUT_S", 90.0, minimum=5.0)
# Tope TOTAL de la guía (redactar + completar lo que faltó + corregir), que
# corre dentro del mismo POST /adr. Antes eran hasta 3 llamadas de 120 s una
# tras otra (~6 min) con el panel en "generando" y el riesgo de que el cliente
# o un proxy cortara la conexión. Las pasadas opcionales (completar, corregir)
# se saltan si ya no hay tiempo; la guía redactada se entrega igual.
ADR_GUIDE_MAX_SECONDS = env_float("ADR_GUIDE_MAX_SECONDS", 150.0, minimum=10.0)
# Tamaño máximo estimado (tokens) del prompt. Por encima se manda una versión
# compacta (propuesta más corta, respuestas de la elicitación resumidas). El
# plan gratuito de Groq rechaza con 413 una petición de más de 8000 tokens
# contando la respuesta.
ADR_PROMPT_TOKEN_BUDGET = env_int("ADR_PROMPT_TOKEN_BUDGET", 4500, minimum=1000)
# Tope de caracteres de la propuesta que se le pasa al LLM: el ADR incluye la
# propuesta completa igual; al modelo le alcanza con el resumen para redactar
# el plan, y así la llamada cabe en planes con límite de tokens por minuto.
ADR_PROPOSAL_PROMPT_MAX_CHARS = env_int("ADR_PROPOSAL_PROMPT_MAX_CHARS", 8000, minimum=1000)
# Segunda pasada de la guía: si la revisión automática (lint_adr_guide)
# encuentra problemas, se le pide al LLM que corrija SOLO esos puntos. Una sola
# pasada, y se usa solo si queda con menos avisos. ADR_GUIDE_REPAIR=off la
# desactiva (ahorra tokens; los avisos quedan igual en el documento).
ADR_GUIDE_REPAIR = os.getenv("ADR_GUIDE_REPAIR", "on").strip().lower() not in {"off", "0", "false", "no"}

PHASE_LABELS = {
    "requerimientos": "Requerimientos",
    "propuesta": "Propuesta",
    "refinamiento": "Refinamiento",
    "diagram": "Diagrama",
    "revision": "Revisión",
    "final": "Cierre",
}
DECISION_LABELS = {
    "approved": "Aprobada",
    "approve": "Aprobada",
    "modified": "Modificación solicitada",
    "modify": "Modificación solicitada",
    "rejected": "Rechazada",
    "reject": "Rechazada",
}

# Secciones que redacta el LLM, en este orden. Se exigen todas: si falta alguna
# la respuesta se considera incompleta y se usa el aviso de respaldo.
LLM_SECTIONS = (
    "Componentes y responsabilidades",
    "Stack tecnológico recomendado",
    "Consecuencias",
    "Riesgos y mitigaciones",
    "Plan de implementación",
    "Primer sprint",
    "Estructura inicial del repositorio",
    "Preguntas abiertas",
)


class AdrNotReadyError(Exception):
    """Falta el insumo mínimo (una propuesta aprobada) para armar el ADR."""


@dataclass
class AdrDecision:
    phase: str
    decision: str
    feedback: Optional[str]
    created_at: Optional[datetime]


@dataclass
class AdrContext:
    project_name: str
    project_description: str
    current_phase: Optional[str]
    resumen: dict = field(default_factory=dict)
    preguntas_respuestas: list[dict] = field(default_factory=list)
    proposal_markdown: str = ""
    proposal_iteration: Optional[int] = None
    proposal_lifecycle: Optional[str] = None
    proposal_feedback_history: list[str] = field(default_factory=list)
    citations: list[dict] = field(default_factory=list)
    mermaid: Optional[str] = None
    diagram_approved: bool = False
    decisions: list[AdrDecision] = field(default_factory=list)
    # Cambios pedidos en la fase Revisión ("Solicitar cambios"), en orden.
    revision_feedback: list[str] = field(default_factory=list)
    # ISO del momento en que se aprobó el ADR (lo pone el endpoint /approve).
    # El estado del documento sale de aquí, no de la fase del proyecto.
    approved_at: Optional[str] = None
    # Adjunto (captura) del diagrama que se usó: el panel muestra esa imagen,
    # así la imagen y el Mermaid del ADR son siempre el mismo diagrama.
    diagram_attachment_id: Optional[str] = None
    # Por qué no se pudo redactar la sección 7 (llm_errors: too_large,
    # rate_limit, timeout, incomplete, error). Solo para el aviso al usuario.
    guide_failure: Optional[str] = None


# --- Recolección (DB) ---------------------------------------------------------


def _content_to_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        for key in ("markdown", "content", "text"):
            value = content.get(key)
            if isinstance(value, str):
                return value
    return str(content)


def _approved_mermaid(
    db: Session, *, user_id: int, project_id: int
) -> tuple[Optional[str], bool, Optional[str]]:
    """Mermaid del diagrama aprobado más reciente; si ninguno está aprobado, el
    del último diagrama generado. Devuelve ``(codigo, aprobado, attachment_id)``.

    "Aprobado" es la ÚLTIMA decisión de cada diagrama (``latest_diagram_decisions``,
    la misma que usa el historial de diagramas del panel): un diagrama que se
    aprobó y después se rechazó ya no cuenta como aprobado.
    """
    rows = (
        db.query(Message)
        .filter(
            Message.project_id == project_id,
            Message.user_id == user_id,
            Message.role == "assistant",
        )
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(200)
        .all()
    )
    candidates: list[tuple[str, list[str]]] = []
    for row in rows:
        code = extract_mermaid_block(row.content or "")
        if not code:
            continue
        # El mensaje guarda el Mermaid tal como lo escribió el modelo; la app
        # lo sanea solo para dibujarlo. En el .md del ADR quedaban etiquetas
        # como EXTR[Extracción (Python + SQLAlchemy)] sin comillas, que otros
        # visores de Mermaid (GitHub, GitLab) no pueden dibujar.
        code = sanitize_mermaid(code)
        attachments = [
            att for att in (row.attachments or []) if isinstance(att, dict) and att.get("id")
        ]
        # La captura del diagrama (kind=screenshot) es la que lista el
        # historial de diagramas del panel; se usa esa para que coincidan.
        screenshots = [att for att in attachments if att.get("kind") == "screenshot"]
        ids = [str(att["id"]) for att in (screenshots or attachments)]
        candidates.append((code, ids))
    if not candidates:
        return None, False, None

    decisions = latest_diagram_decisions(
        db,
        project_id=project_id,
        attachment_ids=[att_id for _code, ids in candidates for att_id in ids],
    )
    for code, ids in candidates:
        approved = next((att_id for att_id in ids if decisions.get(att_id) == "approve"), None)
        if approved:
            return code, True, approved
    code, ids = candidates[0]
    return code, False, (ids[0] if ids else None)


def collect_adr_context(db: Session, *, user_id: int, project_id: int) -> AdrContext:
    """Junta todo lo decidido en el proyecto. Lanza ``AdrNotReadyError`` si
    todavía no hay una propuesta aprobada: sin decisión no hay ADR."""
    project = db.get(Project, project_id)
    if project is None:
        raise AdrNotReadyError("Proyecto no encontrado")

    proposals = (
        db.query(Proposal)
        .filter(Proposal.project_id == project_id)
        .order_by(Proposal.iteration.asc(), Proposal.id.asc())
        .all()
    )
    approved = [p for p in proposals if p.lifecycle == "approved"]
    if not approved:
        raise AdrNotReadyError(
            "Todavía no hay una propuesta aprobada. Aprueba la propuesta antes "
            "de generar el ADR."
        )
    proposal = approved[-1]

    session_row = (
        db.query(UserSession).filter(UserSession.user_id == user_id).first()
    )
    project_state = {}
    if session_row is not None:
        raw = (session_row.engram_state or {}).get(str(project_id))
        project_state = raw if isinstance(raw, dict) else {}
    elicitation = project_state.get(ELICITATION_PHASE) or {}

    mermaid, diagram_approved, diagram_attachment_id = _approved_mermaid(
        db, user_id=user_id, project_id=project_id
    )

    decisions = [
        AdrDecision(
            phase=row.phase,
            decision=row.decision,
            feedback=row.feedback,
            created_at=row.created_at,
        )
        for row in db.query(Approval)
        .filter(Approval.project_id == project_id)
        .order_by(Approval.created_at.asc(), Approval.id.asc())
        .all()
    ]

    return AdrContext(
        project_name=project.name or f"Proyecto {project_id}",
        project_description=(project.description or "").strip(),
        current_phase=project.current_phase,
        resumen=elicitation.get("resumen") or {},
        preguntas_respuestas=list(elicitation.get("preguntas_respuestas") or []),
        proposal_markdown=_content_to_text(proposal.content).strip(),
        proposal_iteration=proposal.iteration,
        proposal_lifecycle=proposal.lifecycle,
        proposal_feedback_history=[
            p.feedback.strip() for p in proposals if (p.feedback or "").strip()
        ],
        citations=list(proposal.citations or []),
        mermaid=mermaid,
        diagram_approved=diagram_approved,
        diagram_attachment_id=diagram_attachment_id,
        decisions=decisions,
    )


# --- Armado (puro) ------------------------------------------------------------


def _as_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _bullets(items: list[str], empty: str = "_No especificado._") -> str:
    return "\n".join(f"- {item}" for item in items) if items else empty


def _demote_headings(markdown: str, levels: int = 2) -> str:
    """Baja los títulos de un markdown embebido para que no compitan con los
    del ADR (un ``# Propuesta`` pasa a ``### Propuesta``)."""

    def repl(match: re.Match) -> str:
        hashes = min(6, len(match.group(1)) + levels)
        return f"{'#' * hashes} {match.group(2)}"

    out_lines = []
    in_fence = False
    for line in markdown.splitlines():
        if line.strip().startswith("```"):
            in_fence = not in_fence
        out_lines.append(line if in_fence else re.sub(r"^(#{1,6})\s+(.*)$", repl, line))
    return "\n".join(out_lines)


def _fmt_date(value: Optional[datetime]) -> str:
    if value is None:
        return "—"
    return value.strftime("%Y-%m-%d %H:%M")


def _cell(text: Optional[str]) -> str:
    return (text or "—").replace("|", "\\|").replace("\n", " ").strip() or "—"


def _references(citations: list[dict]) -> str:
    if not citations:
        return (
            "_La propuesta no recuperó patrones de la base de conocimiento: se basó "
            "en el conocimiento general del modelo._"
        )
    lines = []
    for index, citation in enumerate(citations, start=1):
        name = citation.get("pattern_name") or f"Patrón #{citation.get('pattern_id') or index}"
        similarity = citation.get("similarity")
        sim = f" (similitud {float(similarity) * 100:.0f}%)" if similarity is not None else ""
        lines.append(f"{index}. **{name}**{sim}")
        for source in citation.get("fuentes") or []:
            if isinstance(source, dict) and source.get("url"):
                title = source.get("titulo") or source["url"]
                lines.append(f"   - [{title}]({source['url']})")
    return "\n".join(lines)


def _decision_log(decisions: list[AdrDecision]) -> str:
    if not decisions:
        return "_No hay decisiones registradas._"
    rows = ["| Fecha | Fase | Decisión | Comentario |", "|---|---|---|---|"]
    for item in decisions:
        rows.append(
            f"| {_fmt_date(item.created_at)} "
            f"| {PHASE_LABELS.get(item.phase, item.phase)} "
            f"| {DECISION_LABELS.get(item.decision, item.decision)} "
            f"| {_cell(item.feedback)} |"
        )
    return "\n".join(rows)


def _elicitation_annex(preguntas_respuestas: list[dict]) -> str:
    items = [
        item for item in preguntas_respuestas
        if isinstance(item, dict) and (item.get("pregunta") or item.get("respuesta"))
    ]
    if not items:
        return "_No hay preguntas registradas._"
    # Los ajustes que el usuario pidió al revisar los requerimientos se
    # guardan como pseudo-preguntas; antes salían como "11. (ajuste solicitado
    # por el usuario)" al final de la lista de preguntas.
    questions = [i for i in items if normalize_text(str(i.get("pregunta") or "")).strip() != _ADJUSTMENT]
    adjustments = [i for i in items if i not in questions]
    blocks = []
    for index, item in enumerate(questions, start=1):
        blocks.append(
            f"**{index}. {str(item.get('pregunta') or '').strip()}**\n\n"
            f"{str(item.get('respuesta') or '').strip() or '_Sin respuesta._'}"
        )
    if adjustments:
        blocks.append(
            "**Ajustes pedidos al revisar los requerimientos** (mandan sobre las "
            "respuestas anteriores):\n\n"
            + _bullets([str(i.get("respuesta") or "").strip() for i in adjustments])
        )
    return "\n\n".join(blocks)


_ADJUSTMENT = "(ajuste solicitado por el usuario)"


def _status(ctx: AdrContext) -> str:
    """Estado del ADR según su aprobación (``approved_at``).

    Antes dependía de ``current_phase == "final"``, una fase que no existe en
    este flujo (termina en Revisión): un ADR aprobado se descargaba diciendo
    "Aceptado (pendiente de cierre)" o "Propuesto".
    """
    if ctx.approved_at:
        return "Aceptado"
    return "Propuesto (pendiente de aprobación)"


def _approved_date(ctx: AdrContext) -> str:
    try:
        value = datetime.fromisoformat(str(ctx.approved_at))
    except (TypeError, ValueError):
        return str(ctx.approved_at or "—")
    return value.strftime("%Y-%m-%d")


# Restos de la interfaz que la propuesta trae para la fase Propuesta
# ("- Punto de decisión: ¿Aprueba los trade-offs?"). En el ADR la decisión ya
# está tomada: esas líneas sobran.
_UI_LEFTOVER_RE = re.compile(
    r"^\s*[-*+]?\s*[*_]*punto\s+de\s+decision[*_]*\s*:.*$|^.*¿\s*aprueba[sn]?\b.*\?\s*$",
    re.MULTILINE,
)


def strip_ui_leftovers(markdown: str) -> str:
    """Quita del texto heredado las preguntas dirigidas a la interfaz."""
    lines = [
        line
        for line in (markdown or "").splitlines()
        if not _UI_LEFTOVER_RE.match(normalize_text(line))
    ]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _quality_items(resumen: dict) -> list[str]:
    """Atributos de calidad marcando los que propuso el agente (no el usuario)."""
    origins = resumen.get("calidad_origen") if isinstance(resumen.get("calidad_origen"), dict) else {}
    return [
        f"{item} _(propuesto por el agente, no lo pidió el usuario)_"
        if origins.get(item) == "propuesto"
        else item
        for item in _as_list(resumen.get("calidad"))
    ]


# --- Preocupaciones del dominio ------------------------------------------------


def _user_said_text(ctx: AdrContext) -> str:
    answers = " ".join(
        str(item.get("respuesta") or "")
        for item in ctx.preguntas_respuestas
        if isinstance(item, dict)
    )
    return f"{ctx.project_description} {answers} {' '.join(ctx.revision_feedback)}"


def _requirements_text(ctx: AdrContext) -> str:
    resumen = ctx.resumen or {}
    parts = [
        ctx.project_description,
        str(resumen.get("problema") or ""),
        str(resumen.get("usuarios") or ""),
        " ".join(_as_list(resumen.get("funcionalidades"))),
        " ".join(_as_list(resumen.get("restricciones"))),
        " ".join(_as_list(resumen.get("calidad"))),
        " ".join(str(v) for v in _dict_values(resumen.get("contexto_tecnico"))),
        " ".join(str(v) for v in _dict_values(resumen.get("datos_viabilidad"))),
    ]
    return " ".join(p for p in parts if p) + " " + _user_said_text(ctx)


def _dict_values(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return []
    return [
        str(v).strip()
        for k, v in value.items()
        if not str(k).startswith("_") and isinstance(v, str) and v.strip()
    ]


def open_domain_concerns(ctx: AdrContext, addressed_text: str = "") -> list[DomainConcern]:
    """Preocupaciones del dominio relevantes que nadie respondió.

    Van como preguntas abiertas OBLIGATORIAS en 7.8: no dependen de que el LLM
    se acuerde de que una app de mascotas perdidas necesita mapas. Una
    preocupación cuya pregunta se hizo en la elicitación cuenta como
    respondida aunque la respuesta haya sido "no". ``addressed_text`` (la
    propuesta y la guía) también la cubre: si la guía ya habla de respaldos,
    no se agrega una pregunta genérica que repite lo mismo.
    """
    answered = {
        concern.key
        for item in ctx.preguntas_respuestas
        if isinstance(item, dict) and str(item.get("respuesta") or "").strip()
        for concern in [concern_by_question(str(item.get("pregunta") or ""))]
        if concern is not None
    }
    project_text = _requirements_text(ctx)
    said = _user_said_text(ctx) + " " + " ".join(_as_list((ctx.resumen or {}).get("restricciones")))
    return [
        concern
        for concern in uncovered_concerns(project_text, said)
        if concern.key not in answered
        and not (addressed_text and concern_mentioned(concern, addressed_text))
    ]


# --- Lint de la guía -----------------------------------------------------------

# Cifras que suelen inventarse en la guía: porcentajes (SLA, disponibilidad),
# dinero, capacidad de servidores y latencias. Los plazos ("2 semanas") no se
# revisan: el plan de implementación los necesita y son estimaciones.
_FIGURE_RE = re.compile(
    r"(?:us\$|\$|usd\s*)\s?\d[\d.,]*\s*(?:k|mil)?"
    r"|\d[\d.,]*\s*(?:%|usd|dolares|cop|pesos|vcpus?|cpus?|nucleos|gb|mb|tb|ms|rps|req/s)(?![a-z])"
    r"|\bsla\b[^|\n]{0,20}?\d[\d.,]*\s*%?",
)
_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")


def _numbers(text: str) -> set[str]:
    return {n.replace(",", ".") for n in _NUMBER_RE.findall(text)}


def _section_lines(guide: str, number: str) -> list[str]:
    """Líneas de la subsección ``### 7.<n>`` de la guía."""
    lines = guide.splitlines()
    out: list[str] = []
    inside = False
    for line in lines:
        if re.match(r"^\s*#{1,6}\s", line):
            inside = bool(re.match(rf"^\s*#{{1,6}}\s*{re.escape(number)}\b", line))
            continue
        if inside:
            out.append(line)
    return out


def _table_column(lines: list[str], header_prefix: str) -> list[str]:
    rows = [line for line in lines if line.strip().startswith("|")]
    if len(rows) < 2:
        return []
    headers = [normalize_text(cell).strip(" *`") for cell in rows[0].strip().strip("|").split("|")]
    index = next((i for i, h in enumerate(headers) if h.startswith(header_prefix)), None)
    if index is None:
        return []
    values = []
    for row in rows[2:]:
        cells = row.strip().strip("|").split("|")
        if index < len(cells):
            values.append(cells[index].strip())
    return values


_TECH_WORD_RE = re.compile(r"[a-z][a-z0-9+#.-]{2,}")
_TECH_STOPWORDS = {
    "para", "con", "del", "los", "las", "una", "uno", "por", "base", "datos",
    "servidor", "framework", "libreria", "gestionado", "gestionada", "servicio",
    "nube", "capa", "the", "and",
}


def _source_numbers(ctx: AdrContext) -> set[str]:
    """Números con origen válido para una cifra de la guía.

    Cualquier número de los requerimientos (y de los cambios pedidos), o una
    cifra con unidad de la propuesta. De la propuesta no se toman números
    sueltos: las citas [1]..[3] y la numeración de listas harían pasar "2 vCPU"
    o "3 GB".
    """
    requirements = normalize_text(
        " ".join([_requirements_text(ctx), " ".join(ctx.proposal_feedback_history)])
    )
    proposal_figures = " ".join(
        m.group(0) for m in _FIGURE_RE.finditer(normalize_text(ctx.proposal_markdown))
    )
    return _numbers(requirements) | _numbers(proposal_figures)


def mark_unsourced_figures(ctx: AdrContext, guide: Optional[str]) -> Optional[str]:
    """Marca ``(supuesto)`` cada cifra de la guía que no tiene origen.

    Es el último recurso, sin LLM: si la corrección no las quitó, el lector al
    menos ve que "2 vCPU" o "200 ms" son supuestos y no decisiones.
    """
    if not guide:
        return guide
    sources = _source_numbers(ctx)
    lines = []
    for line in guide.splitlines():
        if ASSUMPTION_MARK in line or "supuesto" in normalize_text(line):
            lines.append(line)
            continue
        # .lower() conserva las posiciones (a diferencia de quitar acentos),
        # así que los índices sirven para insertar en la línea original.
        lowered = line.lower()
        spans = [
            m.span()
            for m in _FIGURE_RE.finditer(lowered)
            if not (_numbers(m.group(0)) & sources)
        ]
        for start, end in reversed(spans):
            while end > start and line[end - 1] == " ":
                end -= 1
            line = f"{line[:end]} {ASSUMPTION_MARK}{line[end:]}"
        lines.append(line)
    return "\n".join(lines)


def _proposal_technologies(proposal: str) -> list[str]:
    """Filas de la tabla de la sección Tecnologías de la propuesta."""
    lines = (proposal or "").splitlines()
    start = next(
        (i for i, line in enumerate(lines) if re.match(r"^\s*#{1,6}\s*[*_\d.]*\s*tecnolog", normalize_text(line))),
        None,
    )
    if start is None:
        return []
    section = []
    for line in lines[start + 1 :]:
        if re.match(r"^\s*#{1,6}\s", line):
            break
        section.append(line)
    return [c for c in _table_column(section, "tecnolog") if c.strip(" -—")]


MAX_GUIDE_TECHNOLOGIES = 6


def lint_adr_guide(ctx: AdrContext, guide: Optional[str]) -> list[str]:
    """Revisión barata y determinista de la guía (sección 7) contra lo decidido.

    Devuelve avisos legibles. Revisa:
      * cifras (porcentajes, dinero, capacidad, latencias) que no aparecen en
        los requerimientos, las respuestas ni la propuesta;
      * tecnologías de 7.2 que la propuesta aprobada no nombra;
      * restos de la interfaz ("Punto de decisión: ¿Aprueba...?").
    Lo que el modelo ya marcó ``(supuesto)`` no se avisa.
    """
    if not guide:
        return []
    warnings: list[str] = []
    source_numbers = _source_numbers(ctx)

    figures: list[str] = []
    for line in guide.splitlines():
        if ASSUMPTION_MARK in line or "supuesto" in normalize_text(line):
            continue
        for match in _FIGURE_RE.finditer(normalize_text(line)):
            figure = match.group(0).strip()
            if not (_numbers(figure) & source_numbers) and figure not in figures:
                figures.append(figure)
    if figures:
        warnings.append(
            "Cifras que no salen de los requerimientos ni de la propuesta: "
            + ", ".join(f"«{f}»" for f in figures)
        )

    proposal = normalize_text(ctx.proposal_markdown + " " + " ".join(ctx.proposal_feedback_history))
    new_tech: list[str] = []
    for cell in _table_column(_section_lines(guide, "7.2"), "tecnolog"):
        if ASSUMPTION_MARK in cell or not cell.strip(" -—"):
            continue
        for part in re.split(r"[/,+;]| y ", re.sub(r"[*_`]", "", cell)):
            words = [
                w for w in _TECH_WORD_RE.findall(normalize_text(re.sub(r"\(.*?\)", "", part)))
                if w not in _TECH_STOPWORDS
            ]
            if words and not any(w in proposal for w in words):
                name = part.strip()
                if name and name not in new_tech:
                    new_tech.append(name)
    if new_tech:
        warnings.append(
            "Tecnologías en 7.2 que la propuesta aprobada no nombra: "
            + ", ".join(new_tech)
        )

    guide_tech = [c for c in _table_column(_section_lines(guide, "7.2"), "tecnolog") if c.strip(" -—")]
    limit = max(MAX_GUIDE_TECHNOLOGIES, len(_proposal_technologies(ctx.proposal_markdown)))
    if len(guide_tech) > limit:
        warnings.append(
            f"Demasiadas tecnologías en 7.2: {len(guide_tech)} (máximo {limit}). Deja las de "
            "la propuesta y solo lo que un requisito exija."
        )

    if any(_UI_LEFTOVER_RE.match(normalize_text(line)) for line in guide.splitlines()):
        warnings.append("La guía repite preguntas de la interfaz (\"¿Aprueba…?\").")
    warnings.extend(_coherence_warnings(ctx, guide))
    return warnings


# Etiquetas internas del sistema que no deben llegar al documento del usuario.
_INTERNAL_LABEL_RE = re.compile(
    r"\brag\b|\bchunks?\b|\bembeddings?\b|\bsimilitud\b|\bsin fuente\b|\[\d+\]"
)
_WORD_RE = re.compile(r"[a-z]{6,}")
_NAME_STOPWORDS = {"del", "los", "las", "con", "para", "por", "una", "uno", "the", "and"}


def _name_tokens(name: str) -> list[str]:
    """Palabras de un nombre de componente para buscarlo en el diagrama
    ("API" -> ["api"]; "Servicio de notificaciones" -> ["servicio", "notificaciones"])."""
    return [
        token
        for token in re.findall(r"[a-z0-9]{3,}", normalize_text(re.sub(r"[*_`]", "", name)))
        if token not in _NAME_STOPWORDS
    ]


def _risk_rows(guide: str) -> list[tuple[str, str, str]]:
    """``(riesgo, impacto, mitigacion)`` de la tabla de 7.4."""
    lines = _section_lines(guide, "7.4")
    risks = _table_column(lines, "riesgo")
    impacts = _table_column(lines, "impacto")
    mitigations = _table_column(lines, "mitigaci")
    rows = []
    for index, risk in enumerate(risks):
        impact = impacts[index] if index < len(impacts) else ""
        mitigation = mitigations[index] if index < len(mitigations) else ""
        rows.append((risk.strip(), normalize_text(impact).strip(" *_"), mitigation.strip()))
    return rows


def _coherence_warnings(ctx: AdrContext, guide: str) -> list[str]:
    """Pasada final de coherencia entre las partes del documento.

    Cada sección se escribe por separado (datos, propuesta, guía del LLM) y
    nadie revisaba que cuadraran. Aquí se comprueba, sin LLM:
      * que los componentes de 7.1 estén en el diagrama;
      * que el primer sprint (7.6) ataque los riesgos de impacto alto;
      * que no haya preguntas repetidas en 7.8;
      * que no se cuelen etiquetas internas (RAG, [n], similitud...).
    """
    warnings: list[str] = []
    if ctx.mermaid:
        diagram = normalize_text(ctx.mermaid)
        missing = [
            component
            for component in _table_column(_section_lines(guide, "7.1"), "componente")
            if component.strip(" -—")
            and not any(word in diagram for word in _name_tokens(component))
        ]
        if missing:
            warnings.append(
                "Componentes de 7.1 que no aparecen en el diagrama: " + ", ".join(missing)
            )

    sprint = normalize_text(" ".join(_section_lines(guide, "7.6")))
    if sprint.strip():
        for risk, impact, mitigation in _risk_rows(guide):
            if not impact.startswith("alto"):
                continue
            words = set(_WORD_RE.findall(normalize_text(f"{risk} {mitigation}")))
            if words and not any(word in sprint for word in words):
                warnings.append(
                    f"El primer sprint no incluye nada sobre el riesgo de impacto alto «{risk}»."
                )

    questions = [
        normalize_text(re.sub(r"[*_`¿?]", "", item.group(1))).strip()
        for line in _section_lines(guide, "7.8")
        for item in [re.match(r"^\s*(?:[-*+]|\d+\.)\s+(.+)$", line)]
        if item
    ]
    repeated = sorted({q for q in questions if questions.count(q) > 1 and q})
    if repeated:
        warnings.append("Preguntas repetidas en 7.8: " + "; ".join(repeated))

    labels = sorted({m.group(0) for m in _INTERNAL_LABEL_RE.finditer(normalize_text(guide))})
    if labels:
        warnings.append(
            "Etiquetas internas del sistema en la guía (no le dicen nada al lector): "
            + ", ".join(labels)
        )
    return warnings


def extract_guide_section(markdown: Optional[str]) -> Optional[str]:
    """La guía (sección 7) tal como quedó en un ADR ya generado.

    Sirve para volver a armar el documento sin llamar al LLM (al aprobarlo).
    ``None`` si el ADR no la tiene (salió con el aviso de respaldo).
    """
    if not markdown:
        return None
    match = re.search(
        r"^## 7\. Guía para empezar\s*\n(.*?)(?=^## Anexo A\.|\Z)", markdown, re.S | re.M
    )
    if not match:
        return None
    body = match.group(1)
    # Lo que agrega el armado (aviso del lint y preguntas obligatorias) se
    # vuelve a calcular: se quita para no duplicarlo.
    body = re.split(r"^> \*\*Revisión automática:\*\*", body, maxsplit=1, flags=re.M)[0]
    body = re.split(r"^\*\*Preguntas abiertas obligatorias", body, maxsplit=1, flags=re.M)[0]
    body = body.strip()
    if not body or body.startswith("> **Aviso:**"):
        return None
    return body


def _guide_block(ctx: AdrContext, llm_sections: Optional[str]) -> str:
    if llm_sections and llm_sections.strip():
        guide = llm_sections.strip()
    else:
        # Antes el aviso mezclaba tres causas posibles y no decía cuál fue.
        cause = (
            f": {llm_error_message(ctx.guide_failure)}"
            if ctx.guide_failure
            else " (no hay un modelo configurado o no respondió)"
        )
        guide = (
            f"> **Aviso:** no se pudo redactar esta parte con el modelo de lenguaje{cause}. "
            "Las secciones 1 a 6 están completas. Usa **Regenerar ADR** para intentarlo de nuevo."
        )
    blocks = [guide]
    concerns = open_domain_concerns(
        ctx, addressed_text=f"{llm_sections or ''} {ctx.proposal_markdown}"
    )
    points = open_points(ctx)
    heading = "" if llm_sections else "### 7.8 Preguntas abiertas\n\n"
    if concerns:
        blocks.append(
            f"{heading}**Preguntas abiertas obligatorias** (preocupaciones habituales "
            "en este tipo de proyecto que nadie respondió todavía):\n\n"
            + "\n".join(f"- **{c.label}:** {c.open_question}" for c in concerns)
        )
        heading = ""
    if points:
        blocks.append(
            f"{heading}**Puntos por confirmar** (supuestos de la propuesta y "
            "verificaciones que pidió el equipo; no se pudieron comprobar desde aquí):\n\n"
            + _bullets(points)
        )
    warnings = lint_adr_guide(ctx, llm_sections)
    if warnings:
        blocks.append(
            "> **Revisión automática:** puntos de la guía que no salen de lo "
            "decidido o que no cuadran con el resto del documento. Revísalos "
            "antes de usarlo.\n"
            + "\n".join(f"> - {w}" for w in warnings)
        )
    return "\n\n".join(blocks)


# --- Resumen ejecutivo ----------------------------------------------------------

_VIABILITY_MARKERS = (
    ("Presupuesto", re.compile(r"presupuest|\busd\b|\$|\bcop\b|dolar|pesos")),
    ("Equipo", re.compile(r"equipo|persona|desarrollador|integrante|somos")),
    ("Plazo", re.compile(r"plazo|\bmes(es)?\b|semana|entrega|\bmvp\b")),
)
_RECOMMENDATION_RE = re.compile(
    r"^\s*[-*+]?\s*[*_]*recomendaci[oó]n[*_]*\s*:\s*(.+)$", re.IGNORECASE | re.MULTILINE
)
_PRIMARY_RE = re.compile(
    r"^\s*[-*+]?\s*[*_]*patr[oó]n principal[*_]*\s*:\s*(.+)$", re.IGNORECASE | re.MULTILINE
)
_PROPOSAL_RISK_RE = re.compile(
    r"^\s*[-*+]?\s*[*_]*riesgos?\s*(?:o|y)\s*costos?[*_]*\s*:\s*(.+)$", re.IGNORECASE | re.MULTILINE
)


def _plain(text: str) -> str:
    """Sin marcas de markdown ni citas [n]: el resumen es para leer, no para auditar."""
    text = re.sub(r"\[(\d+)\]", "", text or "")
    text = re.sub(r"[*_`]", "", text)
    return re.sub(r"\s+", " ", text).strip(" .-")


def _viability_lines(ctx: AdrContext) -> list[str]:
    """Presupuesto, equipo y plazo: primero las palabras del usuario
    (``datos_viabilidad``), después lo que dejó el resumen en restricciones."""
    resumen = ctx.resumen or {}
    literal = resumen.get("datos_viabilidad") if isinstance(resumen.get("datos_viabilidad"), dict) else {}
    restricciones = _as_list(resumen.get("restricciones"))
    lines = []
    for label, pattern in _VIABILITY_MARKERS:
        found = str(literal.get(label.lower()) or "").strip() or next(
            (r for r in restricciones if pattern.search(normalize_text(r))), None
        )
        lines.append(f"**{label}:** {_plain(found) if found else 'no definido'}")
    return lines


_IMPACT_ORDER = {"alto": 0, "alta": 0, "medio": 1, "media": 1, "bajo": 2, "baja": 2}


def _summary_risks(ctx: AdrContext, guide: Optional[str]) -> list[str]:
    # De mayor a menor impacto: el que puede tumbar el proyecto va primero.
    rows = sorted(
        (row for row in _risk_rows(guide or "") if _plain(row[0])),
        key=lambda row: _IMPACT_ORDER.get(row[1].split()[0] if row[1] else "", 3),
    )
    risks = [
        f"{_plain(risk)} (impacto {impact.split()[0]})" if impact else _plain(risk)
        for risk, impact, _mitigation in rows
    ][:3]
    if not risks:
        match = _PROPOSAL_RISK_RE.search(ctx.proposal_markdown or "")
        if match and _plain(match.group(1)):
            risks.append(_plain(match.group(1)))
    return risks


_VERIFY_RE = re.compile(r"\b(?:verifica|verificar|confirma|confirmar|valida|validar|comprueba|comprobar|revisa\s+si)\w*\b", re.I)


def _short(text: str, limit: int = 160) -> str:
    text = _plain(re.sub(r"\s*\|\s*", " — ", text.strip().strip("|")))
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "…"


def open_points(ctx: AdrContext) -> list[str]:
    """Supuestos de la propuesta y verificaciones que pidió el equipo.

    Antes, en 7.8 y en el resumen ejecutivo solo salían las preocupaciones
    genéricas del dominio ("Respaldos"): la región de nube que el usuario pidió
    verificar, o las cifras que la propuesta marcó como supuesto, no le
    llegaban a quien lee el documento. Sin LLM: se leen de la propuesta y de
    los comentarios.
    """
    points: list[str] = []
    for line in (ctx.proposal_markdown or "").splitlines():
        if ASSUMPTION_MARK not in line or re.match(r"^\s*\|?\s*-{3,}", line):
            continue
        # Solo la parte que lleva la marca (en una tabla, la celda).
        cells = [c for c in line.split("|") if ASSUMPTION_MARK in c] or [line]
        for cell in cells:
            points.append("Confirmar el supuesto de la propuesta: " + _short(cell.replace(ASSUMPTION_MARK, "")))
    for comment in [*ctx.proposal_feedback_history, *ctx.revision_feedback]:
        for sentence in re.split(r"(?<=[.;!?\n])\s+", str(comment or "")):
            if _VERIFY_RE.search(sentence):
                points.append("Pendiente de verificar (lo pidió el equipo): " + _short(sentence))
    seen: set[str] = set()
    return [p for p in points if not (p in seen or seen.add(p))][:6]


def _summary_pending(ctx: AdrContext, guide: Optional[str]) -> list[str]:
    pending = [
        c.label
        for c in open_domain_concerns(ctx, addressed_text=f"{guide or ''} {ctx.proposal_markdown}")
    ]
    pending.extend(open_points(ctx))
    for line in _section_lines(guide or "", "7.8"):
        item = re.match(r"^\s*(?:[-*+]|\d+\.)\s+(.+)$", line)
        if item and _plain(item.group(1)) and len(pending) < 6:
            pending.append(_plain(item.group(1)))
    seen: set[str] = set()
    return [p for p in pending if not (p in seen or seen.add(p))][:6]


def executive_summary(ctx: AdrContext, guide: Optional[str]) -> str:
    """Resumen de media página para quien no es técnico.

    Todo sale de lo ya decidido, sin llamar al LLM: el problema y los usuarios
    de la elicitación, la recomendación de la propuesta aprobada, presupuesto,
    equipo y plazo de las restricciones, los principales riesgos (7.4 de la
    guía o el "Riesgo o costo" de la propuesta) y lo que falta decidir
    (preguntas obligatorias del dominio y 7.8).
    """
    resumen = ctx.resumen or {}
    problema = _plain(str(resumen.get("problema") or ctx.project_description or "")) or "No especificado"
    usuarios = _plain(str(resumen.get("usuarios") or "")) or "No especificado"
    proposal = ctx.proposal_markdown or ""
    decision = _RECOMMENDATION_RE.search(proposal) or _PRIMARY_RE.search(proposal)
    decision_text = (
        _plain(decision.group(1)) if decision else "ver la sección 3 (Decisión)"
    )
    risks = _summary_risks(ctx, guide)
    pending = _summary_pending(ctx, guide)
    return "\n".join(
        [
            "## Resumen ejecutivo",
            "",
            "> Esta página resume el documento para quien no necesita los detalles "
            "técnicos. El equipo de desarrollo encuentra todo en las secciones 1 a 7.",
            "",
            f"**Qué problema resuelve:** {problema}.",
            "",
            f"**Para quién:** {usuarios}.",
            "",
            f"**Qué se decidió:** construir el sistema como {decision_text}."
            + (" El diagrama aprobado está en la sección 4." if ctx.mermaid else ""),
            "",
            "**Con qué recursos:**",
            "",
            _bullets(_viability_lines(ctx)),
            "",
            "**Principales riesgos:**",
            "",
            _bullets(risks, empty="_No se registraron riesgos._"),
            "",
            "**Qué falta decidir:**",
            "",
            _bullets(pending, empty="_Nada pendiente registrado._"),
        ]
    )


_TECH_CONTEXT_LABELS = (
    ("plataforma", "Plataforma"),
    ("habilidades_equipo", "Habilidades del equipo"),
    ("fuentes_de_datos", "Fuente de los datos"),
    ("tecnologias_no_dominadas", "Tecnologías que el equipo no domina"),
)


_UNDEFINED_TEXT = {"no definido", "no definida", "ninguno", "ninguna", "n/a", "-"}


def _technical_context_block(resumen: dict) -> str:
    """Contexto técnico y datos de viabilidad con las palabras del usuario.

    Son los datos que deciden la arquitectura (plataforma, habilidades, fuente
    de los datos, equipo real); antes se perdían entre fases.
    """
    blocks = []
    escala = str(resumen.get("escala") or "").strip()
    if escala and normalize_text(escala) not in _UNDEFINED_TEXT:
        # Cifras de uso (usuarios, datos, frecuencia): sin ellas la propuesta
        # no puede dimensionar ni justificar costos.
        blocks.append(f"### Escala y volumen\n\n{escala}")
    tecnico = resumen.get("contexto_tecnico") if isinstance(resumen.get("contexto_tecnico"), dict) else {}
    items = [
        f"**{label}:** {str(tecnico.get(key)).strip()}"
        for key, label in _TECH_CONTEXT_LABELS
        if str(tecnico.get(key) or "").strip()
        and not (key == "tecnologias_no_dominadas" and normalize_text(str(tecnico.get(key))) in _UNDEFINED_TEXT)
    ]
    if items:
        blocks.append("### Contexto técnico\n\n" + _bullets(items))
    datos = resumen.get("datos_viabilidad") if isinstance(resumen.get("datos_viabilidad"), dict) else {}
    items = [
        f"**{key.capitalize()}:** «{str(value).strip()}»"
        for key, value in datos.items()
        if not key.startswith("_") and str(value or "").strip()
    ]
    if items:
        blocks.append("### Datos de viabilidad (palabras del usuario)\n\n" + _bullets(items))
    return ("\n" + "\n\n".join(blocks) + "\n") if blocks else ""


def _reader_labels(markdown: str) -> str:
    """Cambia etiquetas internas de la propuesta por otras que entienda el lector.

    La tabla de trade-offs trae la columna "Fuente RAG" y filas "Sin fuente
    RAG": son nombres del sistema. En el ADR los [n] remiten a la sección 5.
    """
    text = re.sub(r"Sin fuente RAG", "Criterio general", markdown or "", flags=re.IGNORECASE)
    return re.sub(r"Fuente RAG", "Referencia (sección 5)", text, flags=re.IGNORECASE)


def render_adr_markdown(
    ctx: AdrContext,
    *,
    llm_sections: Optional[str],
    generated_at: Optional[datetime] = None,
) -> str:
    """Arma el ADR completo. ``llm_sections`` es el markdown redactado por el
    LLM (``## ...`` por sección) o ``None`` si no se pudo generar."""
    generated_at = generated_at or datetime.now(tz=timezone.utc)
    resumen = ctx.resumen or {}
    problema = str(resumen.get("problema") or ctx.project_description or "No especificado.").strip()
    usuarios = str(resumen.get("usuarios") or "No especificado.").strip()

    diagram = (
        f"```mermaid\n{ctx.mermaid.strip()}\n```\n\n"
        + (
            "_Diagrama aprobado en la fase de Refinamiento._"
            if ctx.diagram_approved
            else "_Último diagrama generado (todavía no hay uno aprobado explícitamente)._"
        )
        if ctx.mermaid
        else "_Todavía no se generó un diagrama. Pídelo en la fase de Refinamiento y vuelve a generar el ADR._"
    )

    iterations = (
        f"Iteración {ctx.proposal_iteration}" if ctx.proposal_iteration else "Iteración —"
    )
    feedback = (
        "\n\n**Ajustes pedidos durante las iteraciones:**\n\n"
        + _bullets(ctx.proposal_feedback_history)
        if ctx.proposal_feedback_history
        else ""
    )

    guide = _guide_block(ctx, llm_sections)
    approved_row = f"| Aprobado | {_approved_date(ctx)} |\n" if ctx.approved_at else ""
    proposal = _reader_labels(strip_ui_leftovers(ctx.proposal_markdown))

    return f"""# ADR-001: Arquitectura de {ctx.project_name}

| Campo | Valor |
|---|---|
| Estado | {_status(ctx)} |
| Fecha | {generated_at.strftime('%Y-%m-%d')} |
{approved_row}| Proyecto | {_cell(ctx.project_name)} |
| Fase actual | {PHASE_LABELS.get(ctx.current_phase or '', ctx.current_phase or '—')} |
| Propuesta | {iterations} |
| Generado por | ArchAgent |

> Este documento reúne las decisiones tomadas en cada fase (requerimientos,
> propuesta, refinamiento y revisión) y una guía para empezar a construir el
> sistema. Las secciones 1 a 6 salen directamente de lo aprobado; la sección 7
> es una guía redactada a partir de esas decisiones.

{executive_summary(ctx, llm_sections)}

## 1. Contexto

**Problema que resuelve:** {problema}

**Usuarios:** {usuarios}
{f'''
**Descripción inicial del proyecto:** {ctx.project_description}
''' if ctx.project_description and ctx.project_description != problema else ''}
## 2. Requerimientos

### Funcionalidades

{_bullets(_as_list(resumen.get('funcionalidades')))}

### Restricciones

{_bullets(_as_list(resumen.get('restricciones')))}

### Atributos de calidad

{_bullets(_quality_items(resumen))}
{_technical_context_block(resumen)}
## 3. Decisión

La arquitectura aprobada es la de la propuesta siguiente ({iterations.lower()}),
incluida completa con su análisis de trade-offs y la opción elegida.

{_demote_headings(proposal) or '_La propuesta aprobada no tiene contenido._'}{feedback}

## 4. Diagrama de arquitectura

{diagram}

## 5. Referencias

{_references(ctx.citations)}

## 6. Historial de decisiones

{_decision_log(ctx.decisions)}
{f'''
**Cambios pedidos en la revisión del ADR:**

{_bullets(ctx.revision_feedback)}
''' if ctx.revision_feedback else ''}
## 7. Guía para empezar

{guide}

## Anexo A. Elicitación de requerimientos

{_elicitation_annex(ctx.preguntas_respuestas)}
"""


# --- LLM ----------------------------------------------------------------------


ADR_SYSTEM_PROMPT = """\
Eres un arquitecto de software senior escribiendo la parte práctica de un \
Architecture Decision Record (ADR) para un equipo que va a empezar a \
construir el sistema. Escribe en español, en tuteo, claro y concreto.

Básate ÚNICAMENTE en los requerimientos, la propuesta aprobada y el diagrama \
que se te dan. No cambies la arquitectura elegida ni propongas otra: tu \
trabajo es bajarla a tierra. Si un dato no está (presupuesto, tamaño del \
equipo, plazo), dilo como supuesto en vez de inventarlo.

REGLAS DE VIABILIDAD (las mismas que siguió la propuesta; obligatorias):
{common_rules}{assumption_rules}
Responde SOLO con markdown, sin texto antes ni después, con EXACTAMENTE \
estas secciones, en este orden, cada una con un título de nivel 3 (###):

### 7.1 Componentes y responsabilidades
Tabla con columnas Componente | Responsabilidad | Se comunica con. Usa los \
mismos nombres que el diagrama.

### 7.2 Stack tecnológico recomendado
Tabla con columnas Capa | Tecnología | Por qué. Coherente con la propuesta y \
con las restricciones (presupuesto, equipo, plazo).

### 7.3 Consecuencias
Dos listas: **Positivas** y **Negativas / costos asumidos**.

### 7.4 Riesgos y mitigaciones
Tabla con columnas Riesgo | Impacto (alto/medio/bajo) | Mitigación, ordenada \
de mayor a menor impacto. Todo lo que dependa de un dato que el usuario no \
confirmó (de dónde salen los datos, una integración, la plataforma) es de \
impacto ALTO y va primero: es lo que puede tumbar el proyecto. Cada riesgo \
debe ser de ESTE proyecto, no una lista genérica.

### 7.5 Plan de implementación
Fases numeradas (MVP primero) con objetivo, entregables y criterio de \
terminado de cada una.

### 7.6 Primer sprint
Lista de 6 a 10 tareas concretas y accionables para la primera o segunda \
semana, en orden. Incluye al menos una tarea que ataque cada riesgo de \
impacto alto de 7.4 (por ejemplo, validar la fuente de datos antes de \
construir encima).

### 7.7 Estructura inicial del repositorio
Un bloque de código con el árbol de carpetas propuesto y una línea por \
carpeta explicando qué va ahí.

### 7.8 Preguntas abiertas
Decisiones que el equipo todavía tiene que tomar o datos que faltan. Incluye \
SIEMPRE las preocupaciones del dominio que se te indiquen como pendientes, \
sin repetir una pregunta con otras palabras.

En todo el texto: usa los mismos nombres de componentes que el diagrama, y \
no escribas etiquetas internas del sistema (RAG, [n], similitud, chunk).
""".format(common_rules=COMMON_VIABILITY_RULES, assumption_rules=GUIDE_ASSUMPTION_RULES)


def _adr_prompt(ctx: AdrContext, *, compact: bool = False) -> str:
    """Contexto del ADR para el LLM. ``compact`` recorta la propuesta y las
    respuestas de la elicitación (que repiten el resumen) para no pasar del
    límite de tokens del proveedor en proyectos grandes."""
    limit = min(ADR_PROPOSAL_PROMPT_MAX_CHARS, 4500) if compact else ADR_PROPOSAL_PROMPT_MAX_CHARS
    proposal = ctx.proposal_markdown
    if len(proposal) > limit:
        proposal = proposal[:limit] + "\n[...]"
    resumen = ctx.resumen or {}
    respuestas = "\n".join(
        f"- {item.get('pregunta')}: "
        + (_shorten(str(item.get('respuesta') or ''), 220) if compact else str(item.get('respuesta')))
        for item in ctx.preguntas_respuestas
        if isinstance(item, dict)
    )
    if compact and len(respuestas) > 2000:
        respuestas = respuestas[:2000] + "\n[...]"
    return (
        f"Proyecto: {ctx.project_name}\n"
        f"Descripción: {ctx.project_description or '(no proporcionada)'}\n\n"
        f"Problema: {resumen.get('problema') or '(no especificado)'}\n"
        f"Usuarios: {resumen.get('usuarios') or '(no especificado)'}\n"
        f"Funcionalidades: {_as_list(resumen.get('funcionalidades'))}\n"
        f"Restricciones: {_as_list(resumen.get('restricciones'))}\n"
        f"Atributos de calidad: {_as_list(resumen.get('calidad'))}\n"
        f"Contexto técnico: {resumen.get('contexto_tecnico') or '(no definido)'}\n"
        "Datos de viabilidad con las palabras del usuario (úsalos tal cual, no "
        f"reinterpretes la composición del equipo): {resumen.get('datos_viabilidad') or '(no hay)'}\n\n"
        f"Respuestas de la elicitación:\n{respuestas or '(sin respuestas)'}\n\n"
        f"Propuesta aprobada:\n{strip_ui_leftovers(proposal)}\n\n"
        f"Diagrama aprobado (Mermaid):\n{ctx.mermaid or '(sin diagrama)'}\n"
        + (
            "\nPreocupaciones del dominio sin respuesta (inclúyelas en 7.8 y no "
            "las resuelvas tú con una decisión):\n"
            + "\n".join(
                f"- {c.label}: {c.open_question}"
                for c in open_domain_concerns(ctx, addressed_text=ctx.proposal_markdown)
            )
            + "\n"
            if open_domain_concerns(ctx, addressed_text=ctx.proposal_markdown)
            else ""
        )
        + (
            "\nSupuestos y verificaciones pendientes (van en 7.8; no los des por "
            "confirmados):\n" + "\n".join(f"- {p}" for p in open_points(ctx)) + "\n"
            if open_points(ctx)
            else ""
        )
        + (
            "\nCambios pedidos por el equipo al revisar el ADR (aplícalos en tu "
            "respuesta; el más reciente manda si se contradicen):\n"
            + "\n".join(f"- {item}" for item in ctx.revision_feedback)
            + "\n"
            if ctx.revision_feedback
            else ""
        )
    )


def _shorten(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "…"


def _fit_prompt(ctx: AdrContext, extra: str = "") -> Optional[str]:
    """Prompt que cabe en ``ADR_PROMPT_TOKEN_BUDGET`` (completo o compacto).

    ``None`` si ni el compacto cabe: para las pasadas opcionales es mejor no
    llamar que recibir un 413.
    """
    for compact in (False, True):
        prompt = _adr_prompt(ctx, compact=compact) + extra
        if estimate_tokens(ADR_SYSTEM_PROMPT + prompt) <= ADR_PROMPT_TOKEN_BUDGET:
            return prompt
    return None


async def _invoke(
    model: BaseChatModel,
    messages: list,
    config: dict[str, Any],
    deadline: Optional[float],
) -> Any:
    """``model.ainvoke`` con el menor entre ``ADR_LLM_TIMEOUT_S`` y lo que queda del tope total."""
    timeout = ADR_LLM_TIMEOUT_S
    if deadline is not None:
        remaining = deadline - time.monotonic()
        if remaining < 5:
            raise asyncio.TimeoutError("se agotó el tiempo total de la guía")
        timeout = min(timeout, remaining)
    return await asyncio.wait_for(model.ainvoke(messages, config=config), timeout=timeout)


def _record(diagnostics: Optional[dict], kind: str) -> None:
    if diagnostics is not None:
        diagnostics.setdefault("failure", kind)


def _message_text(response: Any) -> str:
    content = getattr(response, "content", response)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            part.get("text", "") if isinstance(part, dict) else str(part)
            for part in content
        )
    return str(content or "")


def clean_llm_sections(text: str) -> Optional[str]:
    """Normaliza la respuesta del LLM; ``None`` si le falta alguna sección.

    Quita un fence que envuelva toda la respuesta y los títulos de nivel 1/2
    (el ADR ya tiene los suyos), y exige las secciones de ``LLM_SECTIONS``.
    """
    body = (text or "").strip()
    fenced = re.fullmatch(r"```(?:markdown|md)?\s*\n(.*)\n```", body, re.S)
    if fenced:
        body = fenced.group(1).strip()
    body = re.sub(r"^#{1,2}\s+(?!#)", "### ", body, flags=re.M)
    # Sin acentos ni mayúsculas: "Stack tecnologico" vale igual que
    # "Stack tecnológico". Antes una tilde de menos descartaba toda la
    # sección 7 después de haber gastado los tokens.
    normalized = normalize_text(body)
    if not body or any(normalize_text(section) not in normalized for section in LLM_SECTIONS):
        return None
    return body


async def generate_llm_sections(
    model: BaseChatModel,
    ctx: AdrContext,
    *,
    callbacks: Optional[list[Any]] = None,
    deadline: Optional[float] = None,
    diagnostics: Optional[dict] = None,
) -> Optional[str]:
    """Pide al LLM la guía práctica. Nunca lanza: ante cualquier falla devuelve
    ``None`` y el ADR se arma sin esa parte. ``diagnostics["failure"]`` queda
    con la causa (``too_large``, ``rate_limit``, ``timeout``, ``incomplete``,
    ``error``) para decírsela al usuario."""
    prompt = _fit_prompt(ctx) or _adr_prompt(ctx, compact=True)
    messages = [SystemMessage(content=ADR_SYSTEM_PROMPT), HumanMessage(content=prompt)]
    config: dict[str, Any] = {"run_name": "adr-guide"}
    if callbacks:
        config["callbacks"] = callbacks
    try:
        response = await _invoke(model, messages, config, deadline)
    except Exception as exc:  # noqa: BLE001 -- el ADR se entrega igual
        kind = classify_llm_error(exc)
        _record(diagnostics, kind)
        _LOGGER.warning("ADR: el LLM falló [%s] (%s: %s)", kind, type(exc).__name__, exc)
        return None
    raw = _message_text(response)
    sections = clean_llm_sections(raw)
    if sections is not None:
        return sections
    missing = missing_guide_sections(raw)
    finish_reason = (getattr(response, "response_metadata", None) or {}).get("finish_reason")
    _LOGGER.warning(
        "ADR: la respuesta del LLM no trae todas las secciones (faltan: %s; finish_reason=%s)",
        ", ".join(missing),
        finish_reason,
    )
    # Antes la guía entera se perdía si faltaba UNA subsección (casi siempre
    # las últimas, cuando la respuesta se cortaba). Si llegó una parte, se
    # piden solo las que faltan y se combinan.
    if not raw.strip() or len(missing) == len(LLM_SECTIONS):
        _record(diagnostics, INCOMPLETE)
        return None
    completion_prompt = _fit_prompt(
        ctx,
        "\n\n"
        + _COMPLETE_INSTRUCTIONS.format(
            missing="\n".join(
                f"### 7.{LLM_SECTIONS.index(title) + 1} {title}" for title in missing
            ),
            guide=_guide_digest(raw),
        ),
    )
    if completion_prompt is None:
        _record(diagnostics, TOO_LARGE)
        _LOGGER.warning("ADR: no se piden las secciones que faltan: el prompt pasaría del límite")
        return None
    completion = [SystemMessage(content=ADR_SYSTEM_PROMPT), HumanMessage(content=completion_prompt)]
    try:
        response = await _invoke(
            model, completion, {**config, "run_name": "adr-guide-complete"}, deadline
        )
    except Exception as exc:  # noqa: BLE001 -- el ADR se entrega igual
        kind = classify_llm_error(exc)
        _record(diagnostics, kind)
        _LOGGER.warning("ADR: no se pudo completar la guía [%s] (%s: %s)", kind, type(exc).__name__, exc)
        return None
    sections = clean_llm_sections(merge_guide_sections(raw, _message_text(response)))
    if sections is None:
        _record(diagnostics, INCOMPLETE)
        _LOGGER.warning("ADR: la guía sigue incompleta después de pedir las secciones que faltaban")
    return sections


_COMPLETE_INSTRUCTIONS = """\
Tu respuesta anterior quedó incompleta. Devuelve SOLO estas subsecciones, en \
este orden y con estos encabezados exactos (sé breve, sin repetir las demás):
{missing}

Lo que ya escribiste (para que no te contradigas):
{guide}
"""


def _guide_digest(raw: str, limit: int = 2500) -> str:
    """Lo ya escrito, recortado: 7.1 y 7.2 completas (componentes y stack, lo
    que más se puede contradecir) y del resto solo el encabezado.

    Mandar la guía entera junto con el contexto del ADR pasaba de los 8000
    tokens por minuto del plan gratuito de Groq en los proyectos grandes
    (error 413) y la guía se perdía igual.
    """
    sections = _split_guide_sections(raw)
    parts = [
        text if number in {"1", "2"} else text.splitlines()[0]
        for number, text in sorted(sections.items())
    ]
    digest = "\n\n".join(parts)
    return digest[:limit]


def missing_guide_sections(text: str) -> list[str]:
    """Títulos de ``LLM_SECTIONS`` que no aparecen en ``text``."""
    normalized = normalize_text(text)
    return [title for title in LLM_SECTIONS if normalize_text(title) not in normalized]


_GUIDE_SECTION_RE = re.compile(r"^#{1,6}\s*7\.(\d)\b", re.MULTILINE)


def _split_guide_sections(text: str) -> dict[str, str]:
    """``{"1": "### 7.1 ...", ...}`` para cada subsección de la guía."""
    body = (text or "").strip()
    fenced = re.fullmatch(r"```(?:markdown|md)?\s*\n(.*)\n```", body, re.S)
    if fenced:
        body = fenced.group(1)
    matches = list(_GUIDE_SECTION_RE.finditer(body))
    sections = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        sections[match.group(1)] = body[match.start():end].strip()
    return sections


def merge_guide_sections(original: str, partial: str) -> str:
    """Guía con las subsecciones corregidas de ``partial`` y el resto de ``original``."""
    base = _split_guide_sections(original)
    fixes = _split_guide_sections(partial)
    merged = {**base, **{k: v for k, v in fixes.items() if v}}
    return "\n\n".join(merged[k] for k in sorted(merged))


_REPAIR_INSTRUCTIONS = """\
Una revisión automática encontró estos problemas en la guía que escribiste:
{warnings}

Corrige SOLO esos puntos y devuelve la guía completa (7.1 a 7.8) con el mismo \
formato y las mismas secciones. Para cada tipo de problema:
- Cifras o tecnologías que no salen de lo decidido: quítalas o márcalas \
  `(supuesto)`; no inventes otras.
- Componentes que no están en el diagrama: usa los nombres del diagrama.
- Riesgo de impacto alto sin tarea en el primer sprint: agrega en 7.6 una \
  tarea concreta que lo ataque.
- Preguntas repetidas: deja una sola.
- Etiquetas internas (RAG, [n], similitud): reemplázalas por texto que \
  entienda una persona.
- Demasiadas tecnologías en 7.2: deja las de la propuesta y solo lo que un \
  requisito exija.
No cambies lo que no tiene problemas.

Guía a corregir:
{guide}
"""


async def repair_llm_sections(
    model: BaseChatModel,
    ctx: AdrContext,
    guide: str,
    warnings: list[str],
    *,
    callbacks: Optional[list[Any]] = None,
    deadline: Optional[float] = None,
) -> Optional[str]:
    """Segunda pasada: el LLM corrige los problemas que encontró el lint.

    Devuelve la guía corregida SOLO si está completa y tiene menos avisos que
    la original; si no (o si el LLM falla), ``None`` y se usa la original.
    Nunca lanza.
    """
    if not warnings:
        return None
    prompt = _fit_prompt(
        ctx,
        "\n\n"
        + _REPAIR_INSTRUCTIONS.format(warnings="\n".join(f"- {w}" for w in warnings), guide=guide),
    )
    if prompt is None:
        # Guía + contexto pasan del límite del proveedor (413 seguro): la
        # corrección es opcional, se entrega la guía con sus avisos.
        _LOGGER.warning("ADR: no se corrige la guía: el prompt pasaría del límite de tokens")
        return None
    messages = [SystemMessage(content=ADR_SYSTEM_PROMPT), HumanMessage(content=prompt)]
    config: dict[str, Any] = {"run_name": "adr-guide-repair"}
    if callbacks:
        config["callbacks"] = callbacks
    try:
        response = await _invoke(model, messages, config, deadline)
    except Exception as exc:  # noqa: BLE001 -- se queda la guía original
        _LOGGER.warning(
            "ADR: la corrección de la guía falló [%s] (%s: %s)",
            classify_llm_error(exc),
            type(exc).__name__,
            exc,
        )
        return None
    raw = _message_text(response)
    repaired = clean_llm_sections(raw)
    if repaired is None:
        # A veces el modelo devuelve solo las secciones que cambió: se toman
        # esas y el resto sale de la guía original.
        repaired = clean_llm_sections(merge_guide_sections(guide, raw))
    if repaired is None:
        _LOGGER.warning("ADR: la guía corregida vino incompleta; se usa la original")
        return None
    remaining = lint_adr_guide(ctx, repaired)
    if len(remaining) >= len(warnings):
        _LOGGER.info(
            "ADR: la corrección no redujo los avisos (%s -> %s); se usa la original",
            len(warnings),
            len(remaining),
        )
        return None
    _LOGGER.info("ADR: guía corregida (%s -> %s avisos)", len(warnings), len(remaining))
    return repaired


async def generate_guide(
    model: BaseChatModel,
    ctx: AdrContext,
    *,
    callbacks: Optional[list[Any]] = None,
    diagnostics: Optional[dict] = None,
) -> tuple[Optional[str], bool]:
    """Guía del ADR con su revisión: ``(guia, corregida)``.

    1. El LLM redacta la guía (``generate_llm_sections``).
    2. ``lint_adr_guide`` la revisa contra lo decidido y contra el resto del
       documento.
    3. Si hay avisos y ``ADR_GUIDE_REPAIR`` está activo, una segunda llamada
       corrige solo esos puntos (``repair_llm_sections``). Si devuelve solo
       algunas secciones, se combinan con las originales.
    4. Las cifras que sigan sin origen se marcan ``(supuesto)``. Los demás
       avisos que queden se muestran igual en el documento.

    Todo dentro de ``ADR_GUIDE_MAX_SECONDS``. ``diagnostics["failure"]`` dice
    por qué no hubo guía, si no la hubo.
    """
    deadline = time.monotonic() + ADR_GUIDE_MAX_SECONDS
    guide = await generate_llm_sections(
        model, ctx, callbacks=callbacks, deadline=deadline, diagnostics=diagnostics
    )
    if guide is None:
        return None, False
    repaired_flag = False
    if ADR_GUIDE_REPAIR:
        warnings = lint_adr_guide(ctx, guide)
        if warnings:
            repaired = await repair_llm_sections(
                model, ctx, guide, warnings, callbacks=callbacks, deadline=deadline
            )
            if repaired is not None:
                guide, repaired_flag = repaired, True
    # 4. Lo que siga sin origen queda marcado como supuesto (sin LLM).
    return mark_unsourced_figures(ctx, guide), repaired_flag
