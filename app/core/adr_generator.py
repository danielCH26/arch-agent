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

from app.core.env import env_float, env_int
from app.core.mermaid_validator import extract_mermaid_block
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
) -> tuple[Optional[str], bool]:
    """Mermaid del diagrama aprobado más reciente; si ninguno está aprobado, el
    del último diagrama generado. Devuelve ``(codigo, aprobado)``."""
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
    approved_ids = {
        row.attachment_id
        for row in db.query(Approval)
        .filter(
            Approval.project_id == project_id,
            Approval.phase == DIAGRAM_PHASE,
            Approval.attachment_id.isnot(None),
        )
        .order_by(Approval.id.asc())
        .all()
        if row.decision in ("approved", "approve")
    }

    fallback: Optional[str] = None
    for row in rows:
        code = extract_mermaid_block(row.content or "")
        if not code:
            continue
        attachment_ids = {
            att.get("id") for att in (row.attachments or []) if isinstance(att, dict)
        }
        if approved_ids & attachment_ids:
            return code, True
        if fallback is None:
            fallback = code
    return fallback, False


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

    mermaid, diagram_approved = _approved_mermaid(
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
    if ctx.current_phase == "final":
        return "Aceptado"
    return "Aceptado (pendiente de cierre)" if ctx.diagram_approved else "Propuesto"


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

    if llm_sections and llm_sections.strip():
        guide = llm_sections.strip()
    else:
        guide = (
            "> **Aviso:** no se pudo redactar esta parte con el modelo de lenguaje "
            "(límite de uso, tiempo de espera o respuesta incompleta). El resto del "
            "documento está completo. Usa **Regenerar ADR** para intentarlo de nuevo."
        )

    return f"""# ADR-001: Arquitectura de {ctx.project_name}

| Campo | Valor |
|---|---|
| Estado | {_status(ctx)} |
| Fecha | {generated_at.strftime('%Y-%m-%d')} |
| Proyecto | {_cell(ctx.project_name)} |
| Fase actual | {PHASE_LABELS.get(ctx.current_phase or '', ctx.current_phase or '—')} |
| Propuesta | {iterations} |
| Generado por | ArchAgent |

> Este documento reúne las decisiones tomadas en cada fase (requerimientos,
> propuesta, refinamiento y revisión) y una guía para empezar a construir el
> sistema. Las secciones 1 a 6 salen directamente de lo aprobado; la sección 7
> es una guía redactada a partir de esas decisiones.

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

{_bullets(_as_list(resumen.get('calidad')))}

## 3. Decisión

La arquitectura aprobada es la de la propuesta siguiente ({iterations.lower()}),
incluida completa con su análisis de trade-offs y la opción elegida.

{_demote_headings(ctx.proposal_markdown) or '_La propuesta aprobada no tiene contenido._'}{feedback}

## 4. Diagrama de arquitectura

{diagram}

## 5. Referencias

{_references(ctx.citations)}

## 6. Historial de decisiones

{_decision_log(ctx.decisions)}

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
Decisiones que el equipo todavía tiene que tomar o datos que faltan.
"""


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
        f"Propuesta aprobada:\n{proposal}\n\n"
        f"Diagrama aprobado (Mermaid):\n{ctx.mermaid or '(sin diagrama)'}\n"
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
    lowered = body.lower()
    if not body or any(section.lower() not in lowered for section in LLM_SECTIONS):
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
