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
                detail="El modelo está tardando demasiado. Por favor intenta de nuevo.",
            )
        except LLMRateLimitError as e:
            _logger.warning("LLM rate limit in %s: %s", func.__name__, e)
            raise HTTPException(
                status_code=429,
                detail="Demasiadas solicitudes. Por favor intenta en un minuto.",
            )
        except LLMInvalidResponseError as e:
            _logger.warning("LLM invalid response in %s: %s", func.__name__, e)
            raise HTTPException(
                status_code=502,
                detail="El modelo devolvio una respuesta invalida. Por favor intenta de nuevo.",
            )

    return wrapper


def handle_db_errors(func):
    """Catch database errors and translate them to HTTP responses.

    For DatabaseConnectionError we map to 503 (transient: retry later).
    For DatabaseIntegrityError we map to 409 (client fixed the input and
    should retry with a different value).
    """
    @wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except DatabaseConnectionError as e:
            _logger.error("DB connection error in %s: %s", func.__name__, e)
            raise HTTPException(
                status_code=503,
                detail="Base de datos no disponible. Por favor intenta luego.",
            )
        except DatabaseIntegrityError as e:
            _logger.warning("DB integrity error in %s: %s", func.__name__, e)
            raise HTTPException(
                status_code=409,
                detail="Ya existe un recurso con esos datos.",
            )

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
                detail="Archivo muy grande (maximo 10MB).",
            )
        except FileInvalidFormatError as e:
            _logger.warning("Invalid file format in %s: %s", func.__name__, e)
            raise HTTPException(
                status_code=415,
                detail="Formato no soportado (usa PDF, MD o TXT).",
            )

    return wrapper


def handle_rag_errors(func):
    """Catch RAG errors and translate them to HTTP responses.

    For RAGEmbeddingError we map to 503 (the embedding service is down).
    RAGSearchEmptyError is NOT an HTTP error -- it just means "no results",
    which is a 200 with empty array. The wrapper just lets that exception
    pass through to the caller, which is expected to handle it.
    """
    @wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except RAGEmbeddingError as e:
            _logger.error("RAG embedding error in %s: %s", func.__name__, e)
            raise HTTPException(
                status_code=503,
                detail="No se pudo procesar la consulta. Por favor intenta de nuevo.",
            )
        # RAGSearchEmptyError is NOT an error to the user; let it propagate.

    return wrapper
