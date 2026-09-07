"""Persistence helpers for the new ``messages`` table (F12).

Postgres is the source of truth for chat turns (REQ-1, REQ-3, REQ-4);
``engram_mirror`` fires a best-effort sibling observation to Engram (REQ-6,
ADR-011). Either store degrades gracefully when the other is unreachable.

The helpers accept an explicit ``db: Session`` instead of opening one
internally so the chat route can wrap both ``save_message`` calls in one
transaction (REQ-4: single Postgres tx before ``yield event: done``).
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
) -> Message:
    """Insert a single ``Message`` row.

    Does NOT commit — the caller owns the transaction so both user +
    assistant rows can be persisted atomically (REQ-4).
    """
    _validate_role(role)
    msg = Message(
        session_id=session_id,
        project_id=project_id,
        user_id=user_id,
        role=role,
        content=content,
        citations=_coerce_citations(citations),
    )
    db.add(msg)
    db.flush()  # populate msg.id without committing
    return msg


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
