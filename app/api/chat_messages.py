"""
Chat messages API - GET /api/chat/messages

Provides chat history persistence by fetching messages from interaction_logs
for a specific project.
"""

import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from app.api.dependencies import get_current_user
from app.core.database import SessionLocal
from app.core.session_store import get_or_create_session_for_project
from app.models.interaction_log import InteractionLog
from app.models.session import UserSession
from app.models.project import Project

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat/messages", tags=["chat-messages"])


# --- Response model -----------------------------------------------------------

class ChatMessageResponse(BaseModel):
    id: int
    role: str  # "user" or "assistant"
    content: str
    created_at: str
    latency_ms: int | None = None
    model: str | None = None

    class Config:
        from_attributes = True


# --- Route -------------------------------------------------------------------

@router.get("", response_model=List[ChatMessageResponse])
async def get_chat_messages(
    project_id: int = Query(..., description="Project ID to fetch messages for"),
    current_user: dict = Depends(get_current_user),
):
    """
    Get chat history for a specific project.

    Returns messages ordered by created_at ASC (oldest first).
    Filters by user_id and project_id for privacy (R5).
    """
    user_id = current_user["user_id"]

    db = SessionLocal()
    try:
        # Verify project exists and user has access
        project = db.query(Project).filter(
            Project.id == project_id,
            Project.user_id == user_id,
        ).first()

        if project is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Proyecto no encontrado",
            )

        # Get session for this user-project combination
        session = get_or_create_session_for_project(user_id, project_id)

        # Fetch all interaction logs for this session
        # Note: session stores the active project_id, so we query by session
        # and order by created_at ASC
        logs = (
            db.query(InteractionLog)
            .filter(InteractionLog.session_id == session.id)
            .order_by(InteractionLog.created_at.asc())
            .all()
        )

        # Convert to response format
        messages: List[ChatMessageResponse] = []
        for log in logs:
            # If prompt exists, it's a user message
            if log.prompt:
                messages.append(ChatMessageResponse(
                    id=log.id,
                    role="user",
                    content=log.prompt,
                    created_at=log.created_at.isoformat() if log.created_at else "",
                ))
            # If response exists, it's an assistant message
            if log.response:
                messages.append(ChatMessageResponse(
                    id=log.id,
                    role="assistant",
                    content=log.response,
                    created_at=log.created_at.isoformat() if log.created_at else "",
                    latency_ms=log.latency_ms,
                    model=log.model,
                ))

        return messages

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching chat messages")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al obtener el historial de chat",
        )
    finally:
        db.close()
