"""Retry helper for transient database failures.

Wraps a DB operation with exponential backoff for transient errors
(network blips, pool exhaustion, brief connection drops). After the
configured number of retries, the last exception is re-raised so the
caller can handle it.

Used by F17 error handling infrastructure (issue #25).

Why not just retry everywhere?
    Each call site decides whether retrying is safe. For example,
    duplicate-key inserts should NOT be retried (they'll fail again).
    This helper is for read-mostly operations that benefit from
    transient-failure recovery.

Usage:

    from app.core.db_retry import with_db_retry

    def get_project(user_id, project_id):
        @with_db_retry
        def _op(db):
            return db.query(Project).filter_by(...).first()
        return _op()
"""
from __future__ import annotations

import logging
import time
from functools import wraps
from typing import Any, Callable, TypeVar

from sqlalchemy.exc import OperationalError, DBAPIError

from app.core.exceptions import DatabaseConnectionError

logger = logging.getLogger(__name__)

T = TypeVar("T")

DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_BASE = 0.2  # seconds; 0.2 -> 0.4 -> 0.8


def with_db_retry(
    func: Callable[..., T],
    *,
    max_retries: int = DEFAULT_MAX_RETRIES,
    backoff_base: float = DEFAULT_BACKOFF_BASE,
) -> Callable[..., T]:
    """Decorator: retry ``func`` on transient DB errors.

    Catches SQLAlchemy ``OperationalError`` / ``DBAPIError`` (covers
    connection drops, pool exhaustion, "server closed the connection").
    Does NOT catch integrity errors or programming errors — those should
    surface immediately so the caller can react.

    After ``max_retries`` attempts, re-raises as ``DatabaseConnectionError``
    so ``@handle_db_errors`` decorators upstream map it to HTTP 503.
    """
    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> T:
        last_exc: Exception | None = None
        for attempt in range(max_retries):
            try:
                return func(*args, **kwargs)
            except (OperationalError, DBAPIError) as exc:
                last_exc = exc
                if attempt < max_retries - 1:
                    wait = backoff_base * (2 ** attempt)
                    logger.warning(
                        "DB op %s failed (attempt %s/%s): %s. Retrying in %.2fs",
                        func.__name__,
                        attempt + 1,
                        max_retries,
                        exc,
                        wait,
                    )
                    time.sleep(wait)
        # All retries exhausted — translate to our exception hierarchy
        # so @handle_db_errors converts it to a 503.
        assert last_exc is not None
        logger.error(
            "DB op %s failed after %s attempts: %s",
            func.__name__,
            max_retries,
            last_exc,
        )
        raise DatabaseConnectionError(
            f"DB operation failed after {max_retries} attempts: {last_exc}"
        ) from last_exc

    return wrapper
