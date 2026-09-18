"""
GET /api/chat/attachments/{id} — serve a screenshot with signed-token auth.

The endpoint is intentionally NOT behind ``get_current_user``: an
``<img src=...>`` cannot carry an ``Authorization`` header, so we sign the
URL itself with ``itsdangerous.URLSafeTimedSerializer`` (TTL ≤ 5 min,
REQ-ATT-2). Cross-user access returns **404, NOT 403**, to avoid existence
leak (REQ-ATT-2, SCN-ATT-4) — and the route does NOT log at WARNING on
the 404 case for the same reason.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy.exc import SQLAlchemyError

from app.core.attachment_tokens import (
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
) -> FileResponse:
    """Serve the attachment bytes for ``id`` if the signed URL is valid.

    Auth posture:
      * ``token`` is REQUIRED (returns 401 if missing/expired/forged).
      * The signed payload binds ``(attachment_id, user_id)``. When
        ``token`` verifies but the row's owner differs, the lookup
        returns ``[]`` (no row) and the route returns 404 — same as the
        unknown-id path (defense in depth, REQ-ATT-2 SCN-ATT-4).

    Args:
        id: Attachment UUID (the value the row's ``attachments[].id``
            column holds).
        token: Signed query-string token (TTL 5 min, REQ-ATT-2).

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

    # Defense in depth: we need the user_id to verify the token. The
    # signed payload carries it, but we re-verify against the URL params
    # so a tampered ``id`` in the path can't slip through.
    # Walk the messages table for a row whose attachments JSONB contains
    # the requested id. The token's user_id claim scopes the lookup.
    from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
    from app.core.attachment_tokens import _derive_key, _SALT

    serializer = URLSafeTimedSerializer(_derive_key(), salt=_SALT)
    try:
        payload = serializer.loads(token, max_age=300)
    except SignatureExpired:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired"
        )
    except BadSignature:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        )

    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        )
    if payload.get("aid") != id:
        # The signed id does not match the path id → treat as forged.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        )

    try:
        user_id = int(payload.get("uid"))
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        )

    # Look up the row. JSONB containment is delegated to the adapter via
    # a portable ``JSON_EXTRACT``-style path: we read all messages for
    # the user and filter in Python. Keeps the query portable across
    # SQLite (tests) + Postgres (prod) without ``@>`` operator coupling.
    db = SessionLocal()
    try:
        try:
            rows: list[Message] = (
                db.query(Message)
                .filter(Message.user_id == user_id)
                .all()
            )
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

        attachment = None
        owner_row: Message | None = None
        for row in rows:
            for att in (row.attachments or []):
                if isinstance(att, dict) and att.get("id") == id:
                    attachment = att
                    owner_row = row
                    break
            if attachment is not None:
                break

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


__all__ = ["router"]