"""Custom exceptions for arch-agent backend.

This module defines a hierarchy of custom exceptions used throughout the
backend to signal different kinds of failures. Each exception type is
designed to be caught at the appropriate layer (API endpoint, service,
or background job) and translated into an HTTP response, a logged
warning, or a graceful retry.

Hierarchy:
    ArchAgentError (base)
    +-- LLMError (LLM-related)
    |   +-- LLMTimeoutError
    |   +-- LLMRateLimitError
    |   +-- LLMInvalidResponseError
    +-- RAGError (RAG-related)
    |   +-- RAGEmbeddingError
    |   +-- RAGSearchEmptyError
    +-- FileValidationError (file uploads)
    |   +-- FileTooLargeError
    |   +-- FileInvalidFormatError
    +-- DatabaseError (DB operations)
        +-- DatabaseConnectionError
        +-- DatabaseIntegrityError

Why this hierarchy matters:
    - Endpoint code can do `except LLMTimeoutError` and return a 504
      with a clear message, instead of catching a generic Exception
      and returning a generic 500.
    - Logging can be precise: `logger.exception("LLM timeout", extra=...)`
      vs `logger.error("Something failed")`.
    - Tests can assert specific exception types.
"""
from __future__ import annotations


class ArchAgentError(Exception):
    """Base exception for all arch-agent backend errors.

    Use this as the catch-all when you do not care about the specific
    failure mode. Subclasses below cover the cases where you do.
    """
    pass


# --- LLM errors ---


class LLMError(ArchAgentError):
    """Base for LLM-related errors.

    Raised when the LLM provider (OpenAI, Anthropic, MiniMax, etc.)
    fails to produce a usable response.
    """
    pass


class LLMTimeoutError(LLMError):
    """LLM took too long to respond.

    Map to: HTTP 504 Gateway Timeout.
    Suggested UX: "El modelo está tardando, intenta de nuevo."
    """
    pass


class LLMRateLimitError(LLMError):
    """LLM provider rate-limited us.

    Map to: HTTP 429 Too Many Requests.
    Suggested UX: "Demasiadas solicitudes, intenta en 1 minuto."
    Backend: consider a retry with exponential backoff.
    """
    pass


class LLMInvalidResponseError(LLMError):
    """LLM returned malformed/invalid output (not parseable JSON, etc.).

    Map to: HTTP 502 Bad Gateway.
    Suggested UX: "El modelo devolvio una respuesta invalida."
    """
    pass


# --- RAG errors ---


class RAGError(ArchAgentError):
    """Base for RAG (Retrieval-Augmented Generation) errors."""
    pass


class RAGEmbeddingError(RAGError):
    """Embedding model failed to encode the query.

    Map to: HTTP 503 Service Unavailable.
    Suggested UX: "No se pudo procesar la consulta, intenta de nuevo."
    """
    pass


class RAGSearchEmptyError(RAGError):
    """RAG search returned no relevant results.

    Map to: HTTP 200 with empty results list (NOT an error to the user).
    Suggested UX: "No se encontraron documentos relevantes."
    This is a soft error, not a hard one — the chat still works.
    """
    pass


# --- File errors ---


class FileValidationError(ArchAgentError):
    """Base for file upload validation errors."""
    pass


class FileTooLargeError(FileValidationError):
    """File exceeds the maximum allowed size (currently 10MB).

    Map to: HTTP 413 Payload Too Large.
    Suggested UX: "Archivo muy grande (max 10MB)."
    """
    pass


class FileInvalidFormatError(FileValidationError):
    """File format is not supported (not PDF, MD, or TXT).

    Map to: HTTP 415 Unsupported Media Type.
    Suggested UX: "Formato no soportado (usa PDF, MD o TXT)."
    """
    pass


# --- Database errors ---


class DatabaseError(ArchAgentError):
    """Base for database operation errors."""
    pass


class DatabaseConnectionError(DatabaseError):
    """Cannot connect to the database (network down, pool exhausted).

    Map to: HTTP 503 Service Unavailable.
    Suggested UX: "Base de datos no disponible, intenta luego."
    """
    pass


class DatabaseIntegrityError(DatabaseError):
    """Database integrity constraint violated (unique key, FK, etc.).

    Map to: HTTP 409 Conflict.
    Suggested UX: "Ya existe un recurso con esos datos."
    """
    pass
