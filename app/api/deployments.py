"""
Diagrama de despliegue en la nube.

Endpoints:
    GET  /api/deployments/providers   nubes habilitadas para la demo
    POST /api/deployments/generate    mapea la arquitectura aprobada a una
                                      nube y renderiza el diagrama
    GET  /api/deployments/history     versiones generadas, con su decisión
    POST /api/deployments/decision    aprobar / pedir cambios / rechazar

Depende de HU6: sin un diagrama de arquitectura aprobado no hay nada que
desplegar, y `generate` responde 409 en ese caso.

Las decisiones se registran en `approvals` con ``phase="despliegue"``, no
con "diagram": son dos diagramas distintos del mismo proyecto y aprobar uno
no puede dar por aprobado el otro.
"""

from __future__ import annotations

import logging
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from app.api.dependencies import get_current_user
from app.core.attachment_tokens import build_attachment_url
from app.core.adr_generator import AdrNotReadyError, collect_adr_context
from app.core.cloud_catalog import CloudCatalogError, list_providers
from app.core.database import SessionLocal
from app.core.deployment_diagram import render_deployment_diagram, take_page
from app.core.deployment_mapper import build_plan, plan_to_dict
from app.core.message_store import ensure_user_session, save_message
from app.core.session_store import latest_diagram_decisions, record_approval_decision
from app.models.message import Message
from app.models.project import Project

_LOGGER = logging.getLogger(__name__)

router = APIRouter(prefix="/api/deployments", tags=["deployments"])

PHASE = "despliegue"
ATTACHMENT_KIND = "deployment"

# Mismo tope que el historial de diagramas de arquitectura.
HISTORY_MESSAGE_LOOKBACK = 200


# --------------------------------------------------------------------------
# Esquemas
# --------------------------------------------------------------------------


class ProviderOut(BaseModel):
    id: str
    name: str
    short_name: str
    color: str
    docs_url: str
    service_count: int


class ProvidersOut(BaseModel):
    providers: list[ProviderOut]


class GenerateIn(BaseModel):
    project_id: int = Field(..., ge=1)
    provider: str


class MappedOut(BaseModel):
    component: str
    service_id: str
    service_name: str
    category: str
    category_label: str
    summary: str
    deploy_note: str
    matched_term: str


class GenerateOut(BaseModel):
    provider: dict
    components: list[MappedOut]
    connections: list[dict]
    bridges: list[dict]
    unmapped: list[str]
    dropped_connections: list[dict]
    # None cuando el render falló: la tabla de mapeo sigue siendo útil, así
    # que no se responde error -- se informa que no hay imagen.
    attachment_id: Optional[str] = None
    url: Optional[str] = None
    render_error: Optional[str] = None


class DeploymentVersionOut(BaseModel):
    message_id: int
    id: str
    url: str
    provider: Optional[str] = None
    created_at: str
    decision: Optional[Literal["approve", "modify", "reject"]] = None


class DeploymentHistoryOut(BaseModel):
    deployments: list[DeploymentVersionOut]


class DecisionIn(BaseModel):
    project_id: int = Field(..., ge=1)
    attachment_id: str
    decision: Literal["approve", "modify", "reject"]
    feedback: Optional[str] = None


class DecisionOut(BaseModel):
    decision: str
    message: str


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


def _deployment_rows(db, *, user_id: int, project_id: int):
    """Mensajes recientes con adjuntos de este proyecto y usuario."""
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
        .limit(HISTORY_MESSAGE_LOOKBACK)
        .with_entities(Message.id, Message.created_at, Message.attachments)
        .all()
    )


# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------


def has_approved_deployment(*, user_id: int, project_id: int) -> bool:
    """¿Hay un diagrama de despliegue aprobado en este proyecto?

    La usa el endpoint de decisión de fase para no dejar cerrar Refinamiento
    sin haber pasado por el despliegue. Abre su propia sesión porque la
    llaman desde fuera de una transacción.
    """
    db = SessionLocal()
    try:
        rows = _deployment_rows(db, user_id=user_id, project_id=project_id)
        ids = [
            str(att["id"])
            for _m, _c, attachments in rows
            for att in (attachments or [])
            if isinstance(att, dict)
            and att.get("kind") == ATTACHMENT_KIND
            and att.get("id")
        ]
        if not ids:
            return False
        decisions = latest_diagram_decisions(
            db, project_id=project_id, attachment_ids=ids, phase=PHASE
        )
        return any(value == "approve" for value in decisions.values())
    finally:
        db.close()


@router.get("/render/{token}", include_in_schema=False)
def render_page(token: str) -> HTMLResponse:
    """Sirve la página del diagrama para que la cargue Puppeteer.

    SIN autenticación a propósito: quien la pide es el navegador del sidecar,
    que no tiene sesión de usuario. Lo que la protege es que el token es un
    UUID que solo existe durante los dos minutos que dura el render, y que la
    página se borra en cuanto termina. No lleva datos del usuario: es el mismo
    diagrama que ya está viendo en pantalla.

    Va antes de ``/{...}`` con más segmentos por claridad; no choca con
    ``/history`` ni ``/providers`` porque tiene dos segmentos.
    """
    page = take_page(token)
    if page is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Página de render no disponible"
        )
    return HTMLResponse(content=page)


@router.get("/providers", response_model=ProvidersOut)
def providers(_current_user: dict = Depends(get_current_user)) -> ProvidersOut:
    """Nubes habilitadas. Sale del catálogo en disco, así que agregar un
    proveedor es agregar un YAML y sus íconos, sin tocar este archivo."""
    try:
        found = list_providers()
    except CloudCatalogError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"El catálogo de nubes no está disponible: {exc}",
        ) from exc
    return ProvidersOut(
        providers=[
            ProviderOut(
                id=p.id,
                name=p.name,
                short_name=p.short_name,
                color=p.color,
                docs_url=p.docs_url,
                service_count=len(p.services),
            )
            for p in found
        ]
    )


@router.post("/generate", response_model=GenerateOut)
async def generate(
    body: GenerateIn, current_user: dict = Depends(get_current_user)
) -> GenerateOut:
    user_id = current_user["user_id"]

    db = SessionLocal()
    try:
        project = _owned_project(db, project_id=body.project_id, user_id=user_id)
        try:
            context = collect_adr_context(db, user_id=user_id, project_id=body.project_id)
        except AdrNotReadyError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail=str(exc)
            ) from exc

        # Dependencia explícita con HU6: el despliegue se calcula SOBRE la
        # arquitectura aprobada, no sobre un borrador.
        if not context.mermaid or not context.diagram_approved:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Todavía no hay un diagrama de arquitectura aprobado. "
                    "Apruébalo en Refinamiento antes de generar el despliegue."
                ),
            )

        try:
            plan = build_plan(
                provider_id=body.provider,
                mermaid=context.mermaid,
                proposal_markdown=context.proposal_markdown,
            )
        except CloudCatalogError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
            ) from exc

        if not plan.components:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "No se pudo identificar ningún componente desplegable en el "
                    "diagrama aprobado."
                ),
            )

        project_name = project.name or ""
        payload = plan_to_dict(plan)
        # Sobre QUÉ arquitectura se calculó este despliegue. El ADR lo usa
        # para no mostrar el diagrama de arquitectura nuevo junto a una
        # tabla de despliegue calculada sobre la anterior.
        architecture_id = context.diagram_attachment_id
    finally:
        db.close()

    # El render abre una sesión MCP: se hace FUERA de la transacción para no
    # tener la conexión a la base tomada durante los segundos que tarda.
    attachment = await render_deployment_diagram(plan, project_name=project_name)

    if attachment is None:
        _LOGGER.warning(
            "Despliegue %s del proyecto %s: sin imagen; se devuelve solo el mapeo.",
            plan.provider.id,
            body.project_id,
        )
        return GenerateOut(
            **payload,
            attachment_id=None,
            url=None,
            render_error=(
                "No se pudo generar la imagen del diagrama. El mapeo de "
                "componentes a servicios sí está disponible."
            ),
        )

    # Se guarda como mensaje del asistente para que entre en el historial
    # con la misma mecánica que el diagrama de arquitectura.
    db = SessionLocal()
    try:
        session_id = ensure_user_session(db, user_id)
        summary = (
            f"Diagrama de despliegue en {plan.provider.name} "
            f"({len(plan.services)} servicios)."
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
                    "id": attachment["id"],
                    "kind": ATTACHMENT_KIND,
                    "mime": attachment["mime"],
                    "filename": attachment["filename"],
                    "storage_path": attachment["storage_path"],
                    "provider": plan.provider.id,
                    "architecture_attachment_id": architecture_id,
                    # El plan viaja junto al adjunto para que el ADR pueda
                    # escribir la tabla de "dónde va cada pieza" sin tener
                    # que recalcular el mapeo (que dependería de que la
                    # arquitectura no haya cambiado desde entonces).
                    "plan": payload,
                }
            ],
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    return GenerateOut(
        **payload,
        attachment_id=attachment["id"],
        url=build_attachment_url(attachment["id"], user_id),
        render_error=None,
    )


@router.get("/history", response_model=DeploymentHistoryOut)
def history(
    project_id: int = Query(..., ge=1),
    current_user: dict = Depends(get_current_user),
) -> DeploymentHistoryOut:
    user_id = current_user["user_id"]
    db = SessionLocal()
    try:
        _owned_project(db, project_id=project_id, user_id=user_id)
        rows = _deployment_rows(db, user_id=user_id, project_id=project_id)

        found: list[tuple[int, str, str, Optional[str]]] = []
        for message_id, created_at, attachments in rows:
            for att in attachments or []:
                if not isinstance(att, dict):
                    continue
                if att.get("kind") != ATTACHMENT_KIND or not att.get("id"):
                    continue
                found.append(
                    (
                        message_id,
                        str(att["id"]),
                        created_at.isoformat() if created_at else "",
                        att.get("provider"),
                    )
                )

        decisions = latest_diagram_decisions(
            db,
            project_id=project_id,
            attachment_ids=[att_id for _m, att_id, _c, _p in found],
            phase=PHASE,
        )
    finally:
        db.close()

    return DeploymentHistoryOut(
        deployments=[
            DeploymentVersionOut(
                message_id=message_id,
                id=att_id,
                # Se firma al RESPONDER: el token dura 5 minutos, así que una
                # URL guardada se vence (misma razón que en diagrams.py).
                url=build_attachment_url(att_id, user_id),
                provider=provider,
                created_at=created_at,
                decision=decisions.get(att_id),
            )
            for message_id, att_id, created_at, provider in found
        ]
    )


@router.post("/decision", response_model=DecisionOut)
def decide(
    body: DecisionIn, current_user: dict = Depends(get_current_user)
) -> DecisionOut:
    if body.decision == "modify" and not (body.feedback and body.feedback.strip()):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El feedback es obligatorio para 'modify'.",
        )

    user_id = current_user["user_id"]
    db = SessionLocal()
    try:
        _owned_project(db, project_id=body.project_id, user_id=user_id)

        rows = _deployment_rows(db, user_id=user_id, project_id=body.project_id)
        known = {
            att["id"]
            for _m, _c, attachments in rows
            for att in (attachments or [])
            if isinstance(att, dict)
            and att.get("kind") == ATTACHMENT_KIND
            and att.get("id")
        }
        if body.attachment_id not in known:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Diagrama de despliegue no encontrado",
            )

        already = latest_diagram_decisions(
            db,
            project_id=body.project_id,
            attachment_ids=[body.attachment_id],
            phase=PHASE,
        )
        if body.attachment_id in already:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Este diagrama de despliegue ya tiene una decisión registrada.",
            )

        record_approval_decision(
            db,
            user_id=user_id,
            phase=PHASE,
            decision=body.decision,
            feedback=body.feedback,
            project_id=body.project_id,
            attachment_id=body.attachment_id,
        )
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    messages = {
        "approve": "Diagrama de despliegue aprobado.",
        "modify": "Se registró tu solicitud de cambios.",
        "reject": "Diagrama de despliegue rechazado.",
    }
    return DecisionOut(decision=body.decision, message=messages[body.decision])
