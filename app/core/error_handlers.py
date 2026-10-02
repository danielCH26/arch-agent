"""Error handling decorators for the backend.

Decorators that wrap endpoint functions to translate custom exceptions
into clean HTTP responses with consistent error messages. Each decorator
catches a specific family of exceptions and returns the right status code
plus a user-friendly message.

Usage example (in app/api/chat.py):

    from app.core.error_handlers import handle_llm_errors

    @router.post("/chat")
    @handle_llm_errors
    async def chat(...):
        result = await run_agent(...)
        return result

If run_agent raises an LLMTimeoutError, the decorator catches it
and returns HTTP 504 with the right message, instead of crashing
or returning a generic 500.
"""
from __future__ import annotations

import logging
from functools import wraps

from fastapi import HTTPException

from app.core.exceptions import (
    DatabaseConnectionError,
    DatabaseIntegrityError,
    FileInvalidFormatError,
    FileTooLargeError,
    LLMInvalidResponseError,
    LLMRateLimitError,
    LLMTimeoutError,
    RAGEmbeddingError,
)

_logger = logging.getLogger(__name__)


def handle_llm_errors(func):
    """Catch LLM errors and translate them to user-friendly HTTP responses.

    The wrapped function should be `async def`. On any LLMError subclass
    the decorator logs the error with full context, then raises the
    appropriate HTTPException with the message we want the user to see.
    """
    @wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except LLMTimeoutError as e:
            _logger.warning("LLM timeout in %s: %s", func.__name__, e)
            raise HTTPException(
                status_code=504,
                detail="El modelo de IA está tardando más de lo esperado. "
                       "Por favor, intenta de nuevo en unos segundos.",
            ) from e
        except LLMRateLimitError as e:
            _logger.warning("LLM rate limit in %s: %s", func.__name__, e)
            raise HTTPException(
                status_code=429,
                detail="Estás haciendo muchas solicitudes al modelo. "
                       "Espera un minuto e intenta de nuevo.",
            ) from e
        except LLMInvalidResponseError as e:
            _logger.warning("LLM invalid response in %s: %s", func.__name__, e)
            raise HTTPException(
                status_code=502,
                detail="El modelo de IA devolvió una respuesta inválida. "
                       "Por favor, intenta de nuevo o cambia de modelo.",
            ) from e

    return wrapper


def handle_db_errors(func):
    """Catch database errors and translate them to HTTP responses.

    Maps:
    - DatabaseConnectionError -> 503 (transient: retry later).
    - DatabaseIntegrityError -> 409 (client fixed the input and should
      retry with a different value).
    - SQLAlchemy OperationalError / DBAPIError (network down, server gone)
      -> DatabaseConnectionError -> 503.
    - SQLAlchemy IntegrityError (unique/FK violations) -> DatabaseIntegrityError
      -> 409.
    """
    from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError

    @wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except (OperationalError, DBAPIError) as e:
            # Translate SQLAlchemy low-level errors to our typed hierarchy
            # so the rest of the mapping is consistent with the global
            # handler. Wrapping in DatabaseConnectionError preserves the
            # original traceback via `from e`.
            _logger.error("DB connection error in %s: %s", func.__name__, e)
            raise HTTPException(
                status_code=503,
                detail="No pudimos conectar con la base de datos. "
                       "Es un problema temporal, intenta de nuevo en unos segundos.",
            ) from e
        except IntegrityError as e:
            _logger.warning("DB integrity error in %s: %s", func.__name__, e)
            raise HTTPException(
                status_code=409,
                detail="Ya existe un recurso con esos datos. "
                       "Cambia los valores y vuelve a intentar.",
            ) from e
        except DatabaseConnectionError as e:
            _logger.error("DB connection error in %s: %s", func.__name__, e)
            raise HTTPException(
                status_code=503,
                detail="No pudimos conectar con la base de datos. "
                       "Es un problema temporal, intenta de nuevo en unos segundos.",
            ) from e
        except DatabaseIntegrityError as e:
            _logger.warning("DB integrity error in %s: %s", func.__name__, e)
            raise HTTPException(
                status_code=409,
                detail="Ya existe un recurso con esos datos. "
                       "Cambia los valores y vuelve a intentar.",
            ) from e

    return wrapper


def handle_file_errors(func):
    """Catch file upload errors and translate them to HTTP responses.

    FileTooLargeError -> 413 (payload too large).
    FileInvalidFormatError -> 415 (unsupported media type).
    """
    @wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except FileTooLargeError as e:
            _logger.warning("File too large in %s: %s", func.__name__, e)
            raise HTTPException(
                status_code=413,
                detail="El archivo es demasiado grande. "
                       "El tamaño máximo permitido es 10 MB.",
            ) from e
        except FileInvalidFormatError as e:
            _logger.warning("Invalid file format in %s: %s", func.__name__, e)
            raise HTTPException(
                status_code=415,
                detail="El formato del archivo no es compatible. "
                       "Usa PDF, Markdown o texto plano.",
            ) from e

    return wrapper


def handle_rag_errors(func):
    """Catch RAG errors and translate them to HTTP responses.

    For ``RAGEmbeddingError`` we map to 503 (the embedding service is
    down). "No results" is no longer raised — ``similarity_search``
    returns ``([], metrics)`` directly when nothing matched (PR #85
    round 2 feedback), so callers don't need a dedicated empty-results
    branch.
    """
    @wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except RAGEmbeddingError as e:
            _logger.error("RAG embedding error in %s: %s", func.__name__, e)
            raise HTTPException(
                status_code=503,
                detail="No pudimos procesar tu consulta. "
                       "Verifica tu conexión e intenta de nuevo.",
            ) from e

    return wrapper
