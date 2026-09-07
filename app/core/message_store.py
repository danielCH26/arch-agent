"""Persistence helpers for the new ``messages`` table (F12).

Postgres is the source of truth for chat turns (REQ-1, REQ-3, REQ-4);
``engram_mirror`` fires a best-effort sibling observation to Engram (REQ-6,
ADR-011). Either store degrades gracefully when the other is unreachable.

The helpers accept an explicit ``db: Session`` instead of opening one
internally so the chat route can wrap both ``save_message`` calls in one
transaction (REQ-4: single Postgres tx before ``yield event: done``).

F13 (REQ-ATT-1) adds:
  * ``save_attachment`` / ``list_attachments`` — typed dict helpers for
    persisting PNG screenshots produced by the Puppeteer MCP sidecar.
  * ``attachments`` kwarg on ``save_message`` — merges new attachments
    into the row's JSONB column inside the same flush so a failure on
    either side rolls back both the message row AND the new entries
    (atomicity, REQ-ATT-1).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.message import Message
from app.models.session import UserSession

logger = logging.getLogger(__name__)

_ALLOWED_ROLES = {"user", "assistant", "system"}


def _validate_role(role: str) -> None:
    if role not in _ALLOWED_ROLES:
        raise ValueError(
            f"role must be one of {sorted(_ALLOWED_ROLES)}, got {role!r}"
        )


def _coerce_citations(citations: Any) -> list:
    """Normalise ``citations`` into a JSON-serialisable list.

    Accepts None, dict, or list. Defensive: never raises; on bad input
    falls back to ``[]`` so the DB CHECK never trips the insert path.
    """
    if citations is None:
        return []
    if isinstance(citations, (list, dict)):
        return citations
    try:
        return json.loads(citations)
    except (TypeError, ValueError):
        logger.warning("message_store: dropping non-serialisable citations=%r", citations)
        return []


def _coerce_attachments(attachments: Any) -> list:
    """Normalise ``attachments`` into a JSON-serialisable list.

    Mirrors ``_coerce_citations`` — accepts None / list / dict; defensive
    against non-JSON input. F13 stores typed dicts (UUID, kind, mime,
    filename, storage_path, source_url, bytes) in this column.
    """
    if attachments is None:
        return []
    if isinstance(attachments, list):
        return attachments
    if isinstance(attachments, dict):
        return [attachments]
    try:
        parsed = json.loads(attachments)
        return parsed if isinstance(parsed, list) else [parsed]
    except (TypeError, ValueError):
        logger.warning(
            "message_store: dropping non-serialisable attachments=%r", attachments
        )
        return []


def ensure_user_session(db: Session, user_id: int) -> int:
    """Lazy-upsert the per-user ``UserSession`` row and return its id.

    The unique constraint on ``sessions.user_id`` means two parallel
    inserts race only on the inner INSERT — first wins, second sees
    ``IntegrityError`` and re-selects. This avoids a TOCTOU read-then-write.
    """
    existing = db.query(UserSession).filter(UserSession.user_id == user_id).first()
    if existing is not None:
        return existing.id

    db.add(UserSession(user_id=user_id))
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = (
            db.query(UserSession).filter(UserSession.user_id == user_id).first()
        )
        if existing is None:
            # Should be unreachable unless someone dropped the row mid-call.
            raise
        return existing.id

    return db.query(UserSession).filter(UserSession.user_id == user_id).first().id


def save_message(
    db: Session,
    session_id: int,
    project_id: int | None,
    user_id: int,
    role: str,
    content: str,
    citations: Any = None,
    attachments: Any = None,
) -> Message:
    """Insert a single ``Message`` row.

    Does NOT commit — the caller owns the transaction so both user +
    assistant rows can be persisted atomically (REQ-4). F13: ``attachments``
    is merged into the row's JSONB column inside the same ``flush`` so a
    later SQLAlchemy failure rolls back BOTH the row and the merged
    attachment entries (REQ-ATT-1 atomicity).
    """
    _validate_role(role)
    msg = Message(
        session_id=session_id,
        project_id=project_id,
        user_id=user_id,
        role=role,
        content=content,
        citations=_coerce_citations(citations),
        attachments=_coerce_attachments(attachments),
    )
    db.add(msg)
    db.flush()  # populate msg.id without committing
    return msg


def save_attachment(
    db: Session,
    message_id: int,
    kind: str,
    mime: str,
    storage_path: str,
    source_url: str | None,
    size_bytes: int,
    *,
    filename: str | None = None,
    attachment_id: str | None = None,
) -> dict[str, Any]:
    """Append one ``Attachment`` typed dict to ``Message.attachments``.

    Returns the appended dict so the caller can pass it straight to the
    SSE ``event: attachment`` payload (after stripping ``storage_path``).
    Idempotent on the merge: the JSONB column may already contain entries
    from a previous ``save_message`` invocation on the same row.
    """
    import uuid

    if kind != "screenshot":
        # F13 only ships screenshots (REQ-PMCP-1 / spec scope confirmation).
        # Reject anything else early so a future caller does not silently
        # store an unsupported type.
        raise ValueError(f"unsupported attachment kind={kind!r}; F13 supports 'screenshot' only")

    att_id = attachment_id or str(uuid.uuid4())
    att_filename = filename or f"diagram-{int.from_bytes(uuid.uuid4().bytes, 'big')}.png"
    attachment = {
        "id": att_id,
        "kind": kind,
        "mime": mime,
        "filename": att_filename,
        "storage_path": storage_path,
        "source_url": source_url,
        "bytes": int(size_bytes),
    }

    row = db.get(Message, message_id)
    if row is None:
        raise ValueError(f"message_id={message_id} not found; cannot append attachment")

    existing = list(row.attachments or [])
    # Defensive: skip if same id already present (idempotency on retries).
    if any(a.get("id") == att_id for a in existing):
        logger.info(
            "save_attachment: attachment id=%s already on message_id=%s; skipping",
            att_id,
            message_id,
        )
        return attachment

    row.attachments = existing + [attachment]
    db.flush()
    return attachment


def list_attachments(db: Session, message_id: int) -> list[dict[str, Any]]:
    """Return the ``attachments`` JSONB column for a single message row.

    Returns ``[]`` when the row is missing or the column is unset (defensive
    against pre-F13 rows where the column did not exist).
    """
    row = db.get(Message, message_id)
    if row is None:
        return []
    return list(row.attachments or [])


def list_recent(
    db: Session,
    session_id: int,
    project_id: int,
    limit: int = 5,
) -> list[Message]:
    """Return the last ``limit`` messages for (session_id, project_id) newest-first.

    Scopes by BOTH session_id (cross-user isolation) and project_id (REQ-7).
    Without the project_id predicate this leaks messages across projects
    of the same user (UserSession is one-per-user, not one-per-project).
    Ordering is ``created_at DESC, id DESC`` so two messages inserted in
    the same millisecond keep a stable, deterministic order (REQ-3).
    """
    if limit < 1:
        limit = 1
    stmt = (
        select(Message)
        .where(Message.session_id == session_id)
        .where(Message.project_id == project_id)
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(limit)
    )
    return list(db.execute(stmt).scalars().all())


def engram_mirror(
    message: Message,
    *,
    user_id: int,
    project_id: int | None,
) -> None:
    """Fire-and-forget Engram mirror (REQ-6, ADR-011).

    Best-effort: catches any ``EngramError``, logs WARNING, never raises.
    Imported lazily to keep this module importable without Engram reachable.
    """
    try:
        from app.core.engram_client import EngramClient, EngramError

        client = EngramClient()
        # topic_key per (user, project) — ADR-005 / proposal §6 row 4.
        topic_key = f"arch-agent-user-{user_id}"
        if project_id is not None:
            topic_key = f"{topic_key}-project-{project_id}-chat"

        try:
            result = client.save(
                topic_key=topic_key,
                content=message.content,
                title=f"{message.role}:{message.id or 'pending'}",
                observation_type="chat_message",
            )
            observation_id = result.get("id") if isinstance(result, dict) else None
            if observation_id is not None:
                message.engram_observation_id = int(observation_id)
        except EngramError as exc:
            logger.warning(
                "Engram mirror skipped message=%s user=%s: %s",
                getattr(message, "id", None),
                user_id,
                exc,
            )
    except Exception as exc:  # pragma: no cover — defensive belt-and-braces
        logger.warning(
            "Engram mirror crashed message=%s user=%s: %s",
            getattr(message, "id", None),
            user_id,
            exc,
        )
