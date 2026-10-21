"""Clasificación de errores del proveedor del LLM (app/core/llm_errors.py)."""

import asyncio

from app.core.llm_errors import (
    RATE_LIMIT,
    TIMEOUT,
    TOO_LARGE,
    classify_llm_error,
    llm_error_message,
    retry_after_seconds,
)


def test_un_413_de_groq_es_demasiado_grande_aunque_diga_rate_limit():
    exc = RuntimeError(
        "Error code: 413 - Request too large for model `openai/gpt-oss-120b` ... "
        "Limit 8000, Requested 8908 ... 'code': 'rate_limit_exceeded'"
    )
    assert classify_llm_error(exc) == TOO_LARGE
    assert "límite de tokens" in llm_error_message(TOO_LARGE)


def test_un_429_es_limite_por_minuto_y_se_lee_cuanto_esperar():
    exc = RuntimeError("Error code: 429 - Rate limit reached. Please try again in 6.2s.")
    assert classify_llm_error(exc) == RATE_LIMIT
    assert retry_after_seconds(exc) == 6.2
    assert retry_after_seconds(RuntimeError("try again in 500ms")) == 0.5
    assert retry_after_seconds(RuntimeError("sin dato"), default=15) == 15


def test_timeouts():
    assert classify_llm_error(asyncio.TimeoutError()) == TIMEOUT
    assert classify_llm_error(RuntimeError("Request timed out")) == TIMEOUT
