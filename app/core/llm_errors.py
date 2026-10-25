"""Clasificación de los errores del proveedor del LLM para el usuario y los logs.

Antes cada fase mostraba el error crudo del proveedor (``LLM stream failed:
Error code: 413 - {...}``) o un aviso genérico que mezclaba tres causas
("límite de uso, tiempo de espera o respuesta incompleta"). Con la causa
concreta el usuario sabe qué hacer: esperar un minuto, acortar el comentario o
configurar un modelo con más capacidad.

No depende de ningún SDK: se mira el texto y el tipo de la excepción, que es lo
único común a OpenAI, Groq, Ollama, LM Studio...
"""

from __future__ import annotations

import asyncio
import re

TOO_LARGE = "too_large"
RATE_LIMIT = "rate_limit"
TIMEOUT = "timeout"
INCOMPLETE = "incomplete"
ERROR = "error"

_TOO_LARGE_RE = re.compile(
    r"\b413\b|request too large|context[_ ]length|maximum context|too many tokens|"
    r"reduce (?:the length|your message)",
    re.IGNORECASE,
)
_RATE_LIMIT_RE = re.compile(r"\b429\b|rate[_ ]limit|too many requests|quota", re.IGNORECASE)

MESSAGES = {
    TOO_LARGE: (
        "la solicitud superó el límite de tokens del modelo (pasa con proyectos "
        "grandes o comentarios largos). Acorta el comentario o configura un "
        "modelo con más capacidad en Ajustes → LLM"
    ),
    RATE_LIMIT: (
        "el proveedor del modelo alcanzó su límite de uso por minuto. Espera un "
        "minuto e inténtalo de nuevo"
    ),
    TIMEOUT: "el modelo tardó más de lo permitido en responder",
    INCOMPLETE: "el modelo devolvió una respuesta incompleta",
    ERROR: "el proveedor del modelo respondió con un error",
}


def classify_llm_error(exc: BaseException | None) -> str:
    """``too_large`` | ``rate_limit`` | ``timeout`` | ``error``.

    Un 413 se revisa antes que el 429: Groq responde "Request too large ...
    rate_limit_exceeded" cuando UNA petición pasa el límite por minuto, y ahí
    esperar no sirve.
    """
    if exc is None:
        return ERROR
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return TIMEOUT
    text = f"{type(exc).__name__} {exc}"
    if _TOO_LARGE_RE.search(text):
        return TOO_LARGE
    if _RATE_LIMIT_RE.search(text):
        return RATE_LIMIT
    if "timeout" in text.lower() or "timed out" in text.lower():
        return TIMEOUT
    return ERROR


def llm_error_message(kind: str) -> str:
    """Causa en palabras del usuario (sin detalles internos del proveedor)."""
    return MESSAGES.get(kind, MESSAGES[ERROR])


_RETRY_AFTER_RE = re.compile(r"try again in ([\d.]+)\s*(ms|s|m)\b", re.IGNORECASE)


def retry_after_seconds(exc: BaseException | None, default: float = 15.0) -> float:
    """Segundos que el proveedor pide esperar ("Please try again in 6.2s")."""
    match = _RETRY_AFTER_RE.search(str(exc or ""))
    if not match:
        return default
    value, unit = float(match.group(1)), match.group(2).lower()
    return value / 1000 if unit == "ms" else value * 60 if unit == "m" else value


def estimate_tokens(text: str) -> int:
    """Estimación gruesa (~3.5 caracteres por token en español con markdown)."""
    return int(len(text or "") / 3.5) + 1
