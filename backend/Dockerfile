# =============================================================================
# Backend Dockerfile — FastAPI + LangChain RAG + sentence-transformers CPU
#
# Stack:
#   - Python 3.11 slim
#   - FastAPI + uvicorn
#   - LangChain + langchain-community + langchain-postgres
#   - sentence-transformers (CPU-only) + multilingual-e5-small
#   - PGVector para RAG
#   - pypdf para PDFs nativos
#
# NO incluye:
#   - Chainlit (migrado a FastAPI)
#   - unstructured (sacado del stack para reducir imagen)
#   - CUDA wheels (corremos en CPU)
#
# Multi-stage:
#   - builder: instala deps (capa cacheable)
#   - runtime: solo librerias runtime + codigo + uvicorn
#
# Build:
#   docker build -f backend/Dockerfile -t arch-agent-backend .
#
# Imagen final: ~500MB
# Build time:   ~5-8 min en cold cache, ~10s si solo cambia codigo
# =============================================================================

# ---------- Builder ------------------------------------------------------
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # Forzar wheels CPU-only de torch en TODOS los pip install, no solo
    # el primero. Sin esto, sentence-transformers re-baja torch+CUDA
    # cuando se resuelve requirements.txt.
    PIP_EXTRA_INDEX_URL=https://download.pytorch.org/whl/cpu

WORKDIR /app

# libpq-dev para compilar psycopg2 (runtime usa el .so precompilado)
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# 1. Instalar torch CPU-only PRIMERO (capa cacheable, ~200MB)
#    Lo separamos para que cambios en requirements.txt no reinstalen torch.
RUN pip install --prefix=/install \
        torch --index-url https://download.pytorch.org/whl/cpu

# 2. Resto de deps (PIP_EXTRA_INDEX_URL global toma precedence)
COPY requirements.txt .
RUN pip install --prefix=/install -r requirements.txt


# ---------- Runtime ------------------------------------------------------
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    # Cache de modelos HF/sentence-transformers
    HF_HOME=/app/.cache/huggingface \
    SENTENCE_TRANSFORMERS_HOME=/app/.cache/sentence-transformers \
    # Forzar CPU (defensa en profundidad aunque torch sea CPU-only)
    CUDA_VISIBLE_DEVICES=""

# libpq5 (runtime de psycopg2) + curl para healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copiar dependencias instaladas desde el builder
COPY --from=builder /install /usr/local

# Copiar el codigo del backend
COPY server.py ./
COPY app/ ./app/
COPY schema.sql ./
COPY scripts/ ./scripts/
COPY migrations/ ./migrations/

# Crear usuario no-root + directorios con permisos correctos
RUN useradd --create-home --shell /bin/bash appuser \
    && mkdir -p /app/.cache /app/uploads /app/logs \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

# Healthcheck: pega a /docs (2xx/3xx/4xx = vivo, solo 5xx o conn-refused = unhealthy)
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/docs >/dev/null || exit 1

# uvicorn single-process (sentence-transformers carga el modelo en memoria
# del proceso, escalar horizontal requiere refactor a worker pool separado)
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
