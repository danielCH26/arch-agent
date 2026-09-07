"""
Signed query-string tokens for ``GET /api/chat/attachments/{id}``.

The endpoint serves rendered screenshots to an ``<img src=...>`` tag that
cannot carry an ``Authorization`` header — so the only portable auth is a
short-lived signed URL. We use ``itsdangerous.URLSafeTimedSerializer`` for
that:

  * **Key** = SHA-256 of ``JWT_SECRET_KEY`` (same secret the JWT layer
    uses; we just derive a different key so a leak here does not directly
    expose JWT signing material).
  * **Salt** = ``b"attachment-token"`` so the same secret cannot be reused
    to forge a JWT and vice-versa.
  * **TTL** = 300s (5 min) per REQ-ATT-2. Anything tighter than 5 min
    was judged too short for slow clients; anything looser was judged
    too long for an attachment URL that is effectively a bearer token.

The signed payload is ``{attachment_id, user_id}`` (both bound to the
owner). A token verifies ONLY when BOTH the signature is valid AND the
payload matches the requested attachment + user — the latter is what
keeps cross-user 401s indistinguishable from cross-user 404s downstream.
"""
from __future__ import annotations

import hashlib
import json as _json
import logging
import os
from typing import Any

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

_LOGGER = logging.getLogger(__name__)

# TTL (seconds) for attachment URLs. 5 min balances UX (slow clients) and
# security (a leaked URL expires fast enough that the screenshot is gone
# before a curious onlooker can follow it).
DEFAULT_TTL_SECONDS: int = 300

# Salt value. Constant; do not parameterise from env (itsdangerous requires
# it to match between sign and verify).
_SALT: bytes = b"attachment-token"

# Lazy serializer (key is derived from JWT_SECRET_KEY which is loaded via
# dotenv at server boot — tests can monkeypatch the env var).
_serializer: URLSafeTimedSerializer | None = None


def _derive_key() -> bytes:
    """Derive a 32-byte signing key from ``JWT_SECRET_KEY`` via SHA-256.

    Returns:
        32 raw bytes. ``itsdangerous`` uses this directly; no encoding step
        is required because ``URLSafeTimedSerializer`` accepts ``str`` and
        bytes for its key.
    """
    secret = os.getenv("JWT_SECRET_KEY", "") or ""
    return hashlib.sha256(secret.encode("utf-8")).digest()


def _get_serializer() -> URLSafeTimedSerializer:
    global _serializer
    if _serializer is None:
        _serializer = URLSafeTimedSerializer(_derive_key(), salt=_SALT)
    return _serializer


def reset_serializer_for_tests() -> None:
    """Drop the cached serializer. Tests use this after monkeypatching the
    underlying ``JWT_SECRET_KEY`` env var so the next call re-derives the
    key from the new secret."""
    global _serializer
    _serializer = None


def sign_attachment_token(
    attachment_id: str,
    user_id: int,
    ttl: int = DEFAULT_TTL_SECONDS,
) -> str:
    """Return a signed token binding ``attachment_id`` + ``user_id``.

    The token embeds both values inside the signed payload; the receiving
    endpoint verifies the signature AND the payload match.
    """
    payload = {"aid": str(attachment_id), "uid": int(user_id)}
    serializer = _get_serializer()
    return serializer.dumps(payload)


def verify_attachment_token(
    token: str,
    attachment_id: str,
    user_id: int,
    *,
    max_age: int = DEFAULT_TTL_SECONDS,
) -> bool:
    """Return ``True`` iff the token is valid AND binds the right pair.

    Returns ``False`` (not raises) on every failure mode so the route can
    map indistinguishably to 401 — this matches the spec's "avoid info
    leak" posture (REQ-ATT-2).
    """
    if not token:
        return False
    serializer = _get_serializer()
    try:
        payload = serializer.loads(token, max_age=max_age)
    except SignatureExpired:
        _LOGGER.info("attachment_token: expired")
        return False
    except BadSignature:
        _LOGGER.info("attachment_token: bad signature")
        return False
    except Exception as e:  # pragma: no cover — defensive belt-and-braces
        _LOGGER.warning("attachment_token: unexpected verify error: %s", e)
        return False

    if not isinstance(payload, dict):
        return False
    if payload.get("aid") != str(attachment_id):
        return False
    if int(payload.get("uid", -1)) != int(user_id):
        return False
    return True


# ---------------------------------------------------------------------------
# Uploads-dir bootstrap (REQ-ATT-2 / design §3.4)
# ---------------------------------------------------------------------------

_UPLOADS_SUBDIR = "screenshots"


def _ensure_uploads_dir() -> str:
    """Create ``/app/uploads/screenshots/`` if missing.

    Lazy invocation from the attachments route keeps ``server.py`` free of
    lifespan hooks — ``_ensure_uploads_dir`` runs on first hit only.
    Returns the absolute path so callers can build per-attachment file
    paths.
    """
    base = os.getenv("PUPPETEER_UPLOADS_DIR", "/app/uploads")
    target = os.path.join(base, _UPLOADS_SUBDIR)
    os.makedirs(target, exist_ok=True)
    return target


__all__ = [
    "DEFAULT_TTL_SECONDS",
    "sign_attachment_token",
    "verify_attachment_token",
    "reset_serializer_for_tests",
    "_ensure_uploads_dir",
]