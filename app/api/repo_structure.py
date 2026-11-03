"""
Estructura del repositorio: árbol de carpetas por convenciones y patrones.

Endpoints:
    GET  /api/repo-structure/conventions  convenciones disponibles
    POST /api/repo-structure/generate     compone el árbol sobre la
                                          arquitectura aprobada
    GET  /api/repo-structure/history      versiones generadas

Depende de HU6, igual que el despliegue: el árbol se arma sobre los módulos
del diagrama APROBADO, no sobre un borrador, así que `generate` responde 409
cuando no hay diagrama aprobado.

A diferencia del diagrama de despliegue, acá NO hay punto de aprobación ni
puerta de fase: el entregable es texto (un árbol de carpetas) que acompaña al
ADR, y la historia no pide aprobarlo. Si más adelante se decide que sí, el
molde está en `app/api/deployments.py`.

El adjunto que se guarda no tiene archivo: no hay imagen que renderizar, el
árbol es texto. Lleva `id` para poder referenciarlo en el historial y en el
ADR, y el plan completo para que el ADR no tenga que recalcularlo.
"""

from __future__ import annotations

import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.api.dependencies import get_current_user
from app.core.adr_generator import AdrNotReadyError, collect_adr_context
from app.core.convention_catalog import list_conventions
from app.core.database import SessionLocal
from app.core.message_store import ensure_user_session, save_message
from app.core.repo_structure import build_plan, plan_to_dict
from app.models.message import Message
from app.models.project import Project

_LOGGER = logging.getLogger(__name__)

router = APIRouter(prefix="/api/repo-structure", tags=["repo-structure"])

ATTACHMENT_KIND = "repo_structure"

# Mismo tope que el historial de diagramas.
HISTORY_MESSAGE_LOOKBACK = 200

# Páginas que recorre `latest_structure_plan` antes de rendirse (2 000
# mensajes). Es un tope de seguridad, no una expectativa: lo normal es
# encontrar la estructura en la primera página.
_MAX_HISTORY_PAGES = 10


# --------------------------------------------------------------------------
# Esquemas
# --------------------------------------------------------------------------


class ConventionOut(BaseModel):
    convention_id: str
    name: str
    layer: str
    summary: str
    nesting_limit: Optional[int] = None
    fuentes: list[dict] = Field(default_factory=list)


class ConventionsOut(BaseModel):
    conventions: list[ConventionOut]


class GenerateIn(BaseModel):
    project_id: int = Field(..., ge=1)


class GenerateOut(BaseModel):
    attachment_id: Optional[str] = None
    backend: Optional[dict] = None
    frontend: Optional[dict] = None
    modules: list[dict] = Field(default_factory=list)
    lines: list[dict] = Field(default_factory=list)
    tree_text: str = ""
    warnings: list[str] = Field(default_factory=list)
    # Aclaraciones que NO son pendientes. OJO: todo lo que devuelva
    # `plan_to_dict` tiene que estar declarado acá. Pydantic descarta en
    # silencio lo que no esté, así que un campo olvidado no da error en el
    # backend: llega `undefined` al panel y revienta allá, lejos de la causa.
    notes: list[str] = Field(default_factory=list)
    unmatched_layers: list[str] = Field(default_factory=list)
    module_kinds: list[str] = Field(default_factory=list)


class StructureVersionOut(BaseModel):
    message_id: int
    id: str
    created_at: str
    backend_name: Optional[str] = None
    frontend_name: Optional[str] = None
    module_count: int = 0
    tree_text: str = ""
    plan: dict = Field(default_factory=dict)


class StructureHistoryOut(BaseModel):
    structures: list[StructureVersionOut]


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _owned_project(db, *, project_id: int, user_id: int) -> Project:
    project = (
        db.query(Project)
        .filter(Project.id == project_id, Project.user_id == user_id)
        .first()
    )
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Proyecto no encontrado"
        )
    return project


def _structure_rows(db, *, user_id: int, project_id: int, offset: int = 0):
    return (
        db.query(Message)
        .filter(
            Message.project_id == project_id,
            Message.user_id == user_id,
            Message.role == "assistant",
            Message.attachments != None,  # noqa: E711 (comparación JSONB)
            Message.attachments != [],
        )
        .order_by(Message.created_at.desc())
        .offset(offset)
        .limit(HISTORY_MESSAGE_LOOKBACK)
        .with_entities(Message.id, Message.created_at, Message.attachments)
        .all()
    )


def structure_matches_architecture(
    attachment: dict, architecture_attachment_id: Optional[str]
) -> bool:
    """¿Esta estructura se armó sobre la arquitectura que muestra el ADR?

    Misma regla que ``deployment_matches_architecture``: una estructura
    guardada antes de que se registrara el dato no trae
    ``architecture_attachment_id`` y se acepta, porque descartarla dejaría sin
    sección a los ADR ya generados.
    """
    sobre = attachment.get("architecture_attachment_id")
    if not sobre or not architecture_attachment_id:
        return True
    return sobre == architecture_attachment_id


def latest_structure_plan(
    db,
    *,
    user_id: int,
    project_id: int,
    architecture_attachment_id: Optional[str] = None,
) -> Optional[dict]:
    """El plan de la última versión generada, o None si no hay ninguna.

    Lo usa el ADR. Se queda con el adjunto más reciente porque las filas ya
    vienen ordenadas por fecha descendente.

    Pagina en vez de mirar solo los primeros ``HISTORY_MESSAGE_LOOKBACK``
    mensajes: la consulta trae mensajes con CUALQUIER adjunto (diagramas,
    despliegues), así que en un proyecto con mucha actividad la última
    estructura podía quedar fuera de la ventana y el ADR salía sin la sección.
    No se filtra por ``kind`` en SQL porque la columna es ``JSON`` en SQLite y
    ``JSONB`` solo en PostgreSQL: el operador de contención no existe en las
    dos.
    """
    for pagina in range(_MAX_HISTORY_PAGES):
        filas = _structure_rows(
            db,
            user_id=user_id,
            project_id=project_id,
            offset=pagina * HISTORY_MESSAGE_LOOKBACK,
        )
        if not filas:
            return None
        for _message_id, _created_at, attachments in filas:
            for att in attachments or []:
                if not isinstance(att, dict):
                    continue
                if att.get("kind") != ATTACHMENT_KIND:
                    continue
                # El ADR descarta el despliegue que no corresponde a la
                # arquitectura vigente; la estructura tiene que seguir el
                # mismo criterio. Sin esto, aprobar un diagrama nuevo sin
                # volver a generar la estructura dejaba el ADR mostrando el
                # árbol armado sobre el diagrama anterior.
                if not structure_matches_architecture(att, architecture_attachment_id):
                    continue
                plan = att.get("plan")
                if isinstance(plan, dict) and plan:
                    return plan
        if len(filas) < HISTORY_MESSAGE_LOOKBACK:
            return None
    return None


# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------


@router.get("/conventions", response_model=ConventionsOut)
def conventions(_current_user: dict = Depends(get_current_user)) -> ConventionsOut:
    return ConventionsOut(
        conventions=[
            ConventionOut(
                convention_id=c.convention_id,
                name=c.name,
                layer=c.layer,
                summary=c.summary,
                nesting_limit=c.nesting_limit,
                fuentes=[dict(f) for f in c.fuentes],
            )
            for c in list_conventions()
        ]
    )


@router.post("/generate", response_model=GenerateOut)
def generate(
    body: GenerateIn, current_user: dict = Depends(get_current_user)
) -> GenerateOut:
    user_id = current_user["user_id"]

    db = SessionLocal()
    try:
        _owned_project(db, project_id=body.project_id, user_id=user_id)
        try:
            context = collect_adr_context(
                db, user_id=user_id, project_id=body.project_id
            )
        except AdrNotReadyError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail=str(exc)
            ) from exc

        # Dependencia explícita con HU6: los módulos salen del diagrama
        # aprobado. Sobre un borrador el árbol cambiaría en cada iteración.
        if not context.mermaid or not context.diagram_approved:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Todavía no hay un diagrama de arquitectura aprobado. "
                    "Apruébalo en Refinamiento antes de generar la estructura "
                    "del repositorio."
                ),
            )

        plan = build_plan(
            mermaid=context.mermaid,
            proposal_markdown=context.proposal_markdown,
        )
        payload = plan_to_dict(plan)

        if not plan.modules:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "No se identificó ningún módulo en el diagrama aprobado, así "
                    "que no hay estructura que proponer."
                ),
            )

        if not plan.lines:
            # Hay módulos pero ninguna convención reconocida: devolver un árbol
            # vacío sería desconcertante, y adivinar un stack sería inventar.
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "No se reconoció el stack del proyecto en las tecnologías de la "
                    "propuesta, así que no hay una convención oficial que respalde "
                    "un árbol de carpetas. Revisa la sección de tecnologías."
                ),
            )

        attachment_id = str(uuid.uuid4())
        session_id = ensure_user_session(db, user_id)
        convenciones = ", ".join(
            c["name"] for c in (payload["backend"], payload["frontend"]) if c
        )
        summary = (
            f"Estructura de repositorio ({len(plan.modules)} módulos) "
            f"según {convenciones}."
        )
        save_message(
            db,
            session_id=session_id,
            project_id=body.project_id,
            user_id=user_id,
            role="assistant",
            content=summary,
            attachments=[
                {
                    "id": attachment_id,
                    "kind": ATTACHMENT_KIND,
                    # Sin archivo: el entregable es texto. Se deja explícito
                    # para que el visor de adjuntos no intente descargarlo.
                    "mime": "text/plain",
                    "filename": "estructura-repositorio.txt",
                    "architecture_attachment_id": context.diagram_attachment_id,
                    "plan": payload,
                }
            ],
        )
        db.commit()
    except Exception:
        # Cubre también HTTPException: los dos caminos hacen lo mismo
        # (deshacer y relanzar), así que separarlos era ruido.
        db.rollback()
        raise
    finally:
        db.close()

    return GenerateOut(attachment_id=attachment_id, **payload)


@router.get("/history", response_model=StructureHistoryOut)
def history(
    project_id: int = Query(..., ge=1),
    current_user: dict = Depends(get_current_user),
) -> StructureHistoryOut:
    user_id = current_user["user_id"]
    db = SessionLocal()
    try:
        _owned_project(db, project_id=project_id, user_id=user_id)
        # Pagina igual que `latest_structure_plan`: la consulta trae mensajes
        # con CUALQUIER adjunto, así que sin paginar el panel podía no listar
        # una versión que el ADR sí estaba usando.
        rows: list = []
        for pagina in range(_MAX_HISTORY_PAGES):
            pagina_filas = _structure_rows(
                db,
                user_id=user_id,
                project_id=project_id,
                offset=pagina * HISTORY_MESSAGE_LOOKBACK,
            )
            rows.extend(pagina_filas)
            # Una página incompleta es la última: seguir pidiendo era hacer
            # las diez consultas siempre, también en un proyecto de tres
            # mensajes. Mismo corte que `latest_structure_plan`.
            if len(pagina_filas) < HISTORY_MESSAGE_LOOKBACK:
                break

        versiones: list[StructureVersionOut] = []
        for message_id, created_at, attachments in rows:
            for att in attachments or []:
                if not isinstance(att, dict):
                    continue
                if att.get("kind") != ATTACHMENT_KIND or not att.get("id"):
                    continue
                plan = att.get("plan") if isinstance(att.get("plan"), dict) else {}
                backend = plan.get("backend") or {}
                frontend = plan.get("frontend") or {}
                versiones.append(
                    StructureVersionOut(
                        message_id=message_id,
                        id=str(att["id"]),
                        created_at=created_at.isoformat() if created_at else "",
                        backend_name=backend.get("name"),
                        frontend_name=frontend.get("name"),
                        module_count=len(plan.get("modules") or []),
                        tree_text=str(plan.get("tree_text") or ""),
                        plan=plan,
                    )
                )
    finally:
        db.close()

    return StructureHistoryOut(structures=versiones)
