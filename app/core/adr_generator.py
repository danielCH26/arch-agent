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
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy.orm import Session

from app.core.domain_concerns import DomainConcern, concern_by_question, uncovered_concerns
from app.core.env import env_float, env_int
from app.core.mermaid_validator import extract_mermaid_block
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

ADR_LLM_TIMEOUT_S = env_float("ADR_LLM_TIMEOUT_S", 120.0, minimum=5.0)
# Tope de caracteres de la propuesta que se le pasa al LLM: el ADR incluye la
# propuesta completa igual; al modelo le alcanza con el resumen para redactar
# el plan, y así la llamada cabe en planes con límite de tokens por minuto.
ADR_PROPOSAL_PROMPT_MAX_CHARS = env_int("ADR_PROPOSAL_PROMPT_MAX_CHARS", 8000, minimum=1000)

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
    blocks = []
    for index, item in enumerate(items, start=1):
        blocks.append(
            f"**{index}. {str(item.get('pregunta') or '').strip()}**\n\n"
            f"{str(item.get('respuesta') or '').strip() or '_Sin respuesta._'}"
        )
    return "\n\n".join(blocks)


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
    ]
    return " ".join(p for p in parts if p) + " " + _user_said_text(ctx)


def open_domain_concerns(ctx: AdrContext) -> list[DomainConcern]:
    """Preocupaciones del dominio relevantes que nadie respondió.

    Van como preguntas abiertas OBLIGATORIAS en 7.8: no dependen de que el LLM
    se acuerde de que una app de mascotas perdidas necesita mapas. Una
    preocupación cuya pregunta se hizo en la elicitación cuenta como
    respondida aunque la respuesta haya sido "no".
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
    # Origen válido de una cifra: cualquier número de los requerimientos (y de
    # los cambios pedidos), o una cifra con unidad de la propuesta. De la
    # propuesta no se toman números sueltos: las citas [1]..[3] y la
    # numeración de listas harían pasar "2 vCPU" o "3 GB".
    requirements = normalize_text(
        " ".join([_requirements_text(ctx), " ".join(ctx.proposal_feedback_history)])
    )
    proposal_figures = " ".join(
        m.group(0) for m in _FIGURE_RE.finditer(normalize_text(ctx.proposal_markdown))
    )
    source_numbers = _numbers(requirements) | _numbers(proposal_figures)

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

    if any(_UI_LEFTOVER_RE.match(normalize_text(line)) for line in guide.splitlines()):
        warnings.append("La guía repite preguntas de la interfaz (\"¿Aprueba…?\").")
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
        guide = (
            "> **Aviso:** no se pudo redactar esta parte con el modelo de lenguaje "
            "(límite de uso, tiempo de espera o respuesta incompleta). El resto del "
            "documento está completo. Usa **Regenerar ADR** para intentarlo de nuevo."
        )
    blocks = [guide]
    concerns = open_domain_concerns(ctx)
    if concerns:
        heading = "" if llm_sections else "### 7.8 Preguntas abiertas\n\n"
        blocks.append(
            f"{heading}**Preguntas abiertas obligatorias** (preocupaciones habituales "
            "en este tipo de proyecto que nadie respondió todavía):\n\n"
            + "\n".join(f"- **{c.label}:** {c.open_question}" for c in concerns)
        )
    warnings = lint_adr_guide(ctx, llm_sections)
    if warnings:
        blocks.append(
            "> **Revisión automática:** estos datos de la guía no salen de lo "
            "decidido; tómalos como supuestos y confírmalos antes de usarlos.\n"
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
    restricciones = _as_list((ctx.resumen or {}).get("restricciones"))
    lines = []
    for label, pattern in _VIABILITY_MARKERS:
        found = next((r for r in restricciones if pattern.search(normalize_text(r))), None)
        lines.append(f"**{label}:** {_plain(found) if found else 'no definido'}")
    return lines


def _summary_risks(ctx: AdrContext, guide: Optional[str]) -> list[str]:
    risks = [
        _plain(cell)
        for cell in _table_column(_section_lines(guide or "", "7.4"), "riesgo")
        if _plain(cell)
    ][:3]
    if not risks:
        match = _PROPOSAL_RISK_RE.search(ctx.proposal_markdown or "")
        if match and _plain(match.group(1)):
            risks.append(_plain(match.group(1)))
    return risks


def _summary_pending(ctx: AdrContext, guide: Optional[str]) -> list[str]:
    pending = [c.label for c in open_domain_concerns(ctx)]
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
    proposal = strip_ui_leftovers(ctx.proposal_markdown)

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
Tabla con columnas Riesgo | Impacto (alto/medio/bajo) | Mitigación.

### 7.5 Plan de implementación
Fases numeradas (MVP primero) con objetivo, entregables y criterio de \
terminado de cada una.

### 7.6 Primer sprint
Lista de 6 a 10 tareas concretas y accionables para la primera o segunda \
semana, en orden.

### 7.7 Estructura inicial del repositorio
Un bloque de código con el árbol de carpetas propuesto y una línea por \
carpeta explicando qué va ahí.

### 7.8 Preguntas abiertas
Decisiones que el equipo todavía tiene que tomar o datos que faltan. Incluye \
SIEMPRE las preocupaciones del dominio que se te indiquen como pendientes.
""".format(common_rules=COMMON_VIABILITY_RULES, assumption_rules=GUIDE_ASSUMPTION_RULES)


def _adr_prompt(ctx: AdrContext) -> str:
    proposal = ctx.proposal_markdown
    if len(proposal) > ADR_PROPOSAL_PROMPT_MAX_CHARS:
        proposal = proposal[:ADR_PROPOSAL_PROMPT_MAX_CHARS] + "\n[...]"
    resumen = ctx.resumen or {}
    respuestas = "\n".join(
        f"- {item.get('pregunta')}: {item.get('respuesta')}"
        for item in ctx.preguntas_respuestas
        if isinstance(item, dict)
    )
    return (
        f"Proyecto: {ctx.project_name}\n"
        f"Descripción: {ctx.project_description or '(no proporcionada)'}\n\n"
        f"Problema: {resumen.get('problema') or '(no especificado)'}\n"
        f"Usuarios: {resumen.get('usuarios') or '(no especificado)'}\n"
        f"Funcionalidades: {_as_list(resumen.get('funcionalidades'))}\n"
        f"Restricciones: {_as_list(resumen.get('restricciones'))}\n"
        f"Atributos de calidad: {_as_list(resumen.get('calidad'))}\n\n"
        f"Respuestas de la elicitación:\n{respuestas or '(sin respuestas)'}\n\n"
        f"Propuesta aprobada:\n{strip_ui_leftovers(proposal)}\n\n"
        f"Diagrama aprobado (Mermaid):\n{ctx.mermaid or '(sin diagrama)'}\n"
        + (
            "\nPreocupaciones del dominio sin respuesta (inclúyelas en 7.8 y no "
            "las resuelvas tú con una decisión):\n"
            + "\n".join(f"- {c.label}: {c.open_question}" for c in open_domain_concerns(ctx))
            + "\n"
            if open_domain_concerns(ctx)
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
) -> Optional[str]:
    """Pide al LLM la guía práctica. Nunca lanza: ante cualquier falla devuelve
    ``None`` y el ADR se arma sin esa parte."""
    messages = [SystemMessage(content=ADR_SYSTEM_PROMPT), HumanMessage(content=_adr_prompt(ctx))]
    config: dict[str, Any] = {"run_name": "adr-guide"}
    if callbacks:
        config["callbacks"] = callbacks
    try:
        response = await asyncio.wait_for(
            model.ainvoke(messages, config=config), timeout=ADR_LLM_TIMEOUT_S
        )
    except Exception as exc:  # noqa: BLE001 -- el ADR se entrega igual
        _LOGGER.warning("ADR: el LLM falló (%s: %s)", type(exc).__name__, exc)
        return None
    sections = clean_llm_sections(_message_text(response))
    if sections is None:
        _LOGGER.warning("ADR: la respuesta del LLM no trae todas las secciones")
    return sections
