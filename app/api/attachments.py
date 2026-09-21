"""
GET /api/chat/attachments/{id} — serve a screenshot with signed-token auth.

The endpoint requires both a signed token (short-lived bearer) AND an
authenticated session (``get_current_user``). The token authorizes the
specific attachment read; the session provides the user context for
cross-check. Cross-user access returns **404, NOT 403**, to avoid existence
leak (REQ-ATT-2, SCN-ATT-4) — and the route does NOT log at WARNING on
the 404 case for the same reason.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy.exc import SQLAlchemyError

from app.api.auth import get_current_user
from app.core.attachment_tokens import (
    DEFAULT_TTL_SECONDS,
    _ensure_uploads_dir,
    verify_attachment_token,
)
from app.core.database import SessionLocal
from app.models.message import Message

router = APIRouter(prefix="/api/chat", tags=["chat"])
logger = logging.getLogger(__name__)


@router.get("/attachments/{id}")
def get_attachment(
    id: str,
    token: str | None = Query(default=None),
    user_id: int = Depends(get_current_user),
) -> FileResponse:
    """Serve the attachment bytes for ``id`` if the signed URL is valid.

    Auth posture:
      * ``get_current_user`` provides the authenticated user context.
      * ``token`` is REQUIRED (returns 401 if missing/expired/forged).
      * The signed payload binds ``(attachment_id, user_id)``. When
        ``token`` verifies but the row's owner differs, the lookup
        returns ``[]`` (no row) and the route returns 404 — same as the
        unknown-id path (defense in depth, REQ-ATT-2 SCN-ATT-4).

    Args:
        id: Attachment UUID (the value the row's ``attachments[].id``
            column holds).
        token: Signed query-string token (TTL 5 min, REQ-ATT-2).
        user_id: Authenticated user from session (via ``get_current_user``).

    Returns:
        ``FileResponse`` carrying the PNG bytes + ``Content-Type`` from
        the row + ``Content-Disposition: inline; filename="<att>"`` so
        ``<img>`` tags render the file in-browser (REQ-ATT-3, SCN-ATT-6).
    """
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing token",
        )

    # Delegate token verification to the helper. Returns (valid, payload_uid)
    # or (False, None) on any failure — indistinguishably maps to 401.
    valid, payload_uid = verify_attachment_token(
        token,
        attachment_id=id,
        user_id=user_id,
    )
    if not valid or payload_uid != user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )

    # Look up the attachment using dialect-aware helper.
    # Postgres uses JSONB containment with GIN index; SQLite falls back to Python filter.
    db = SessionLocal()
    try:
        try:
            attachment, owner_row = _lookup_attachment(db, user_id, id)
        except SQLAlchemyError as exc:
            logger.warning(
                "attachment lookup DB error user_id=%s attachment_id=%s: %s",
                user_id,
                id,
                exc,
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Not found",
            )

        if attachment is None or owner_row is None:
            # 404, NOT 403 — avoid existence leak (REQ-ATT-2 / SCN-ATT-4).
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Not found"
            )

        storage_path = attachment.get("storage_path")
        if not storage_path:
            # Defensive: a row referencing an attachment without a
            # storage_path is corrupt; treat as not-found.
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Not found"
            )

        # Lazy uploads-dir bootstrap on first hit (kept off server.py's
        # lifespan so that file stays F13-untouched).
        _ensure_uploads_dir()

        mime = attachment.get("mime") or "application/octet-stream"
        filename = attachment.get("filename") or "attachment"

        return FileResponse(
            path=storage_path,
            media_type=mime,
            headers={
                "Content-Disposition": f'inline; filename="{filename}"',
                "Cache-Control": "private, max-age=300",
            },
        )
    finally:
        db.close()


def _lookup_attachment(
    db: SessionLocal, user_id: int, attachment_id: str
) -> tuple[dict | None, Message | None]:
    """Resolve one attachment by ``(user_id, attachment_id)``.

    Postgres path uses ``messages.attachments @> '[{"id": "..."}]'::jsonb``
    + the new GIN index from migration 0013. SQLite path falls back to
    the existing in-Python filter (test compatibility — JSONB containment
    is not supported on SQLite).
    """
    dialect = db.bind.dialect.name if db.bind is not None else ""
    if dialect == "postgresql":
        row = (
            db.query(Message)
            .filter(
                Message.user_id == user_id,
                Message.attachments.contains([{"id": attachment_id}]),
            )
            .first()
        )
        if row is None:
            return None, None
        attachment = next(
            (a for a in (row.attachments or [])
             if isinstance(a, dict) and a.get("id") == attachment_id),
            None,
        )
        return attachment, row

    # SQLite / fallback: existing Python-filter behavior.
    rows: list[Message] = (
        db.query(Message).filter(Message.user_id == user_id).all()
    )
    for row in rows:
        for att in (row.attachments or []):
            if isinstance(att, dict) and att.get("id") == attachment_id:
                return att, row
    return None, None


__all__ = ["router"]