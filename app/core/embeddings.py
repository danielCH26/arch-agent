"""
Embeddings wrapper para HU13 (issue #8).

Modelo: intfloat/multilingual-e5-small (384 dimensiones).

El modelo se baja de HuggingFace la primera vez (~80MB) y queda cacheado en
`/app/.cache/huggingface` (volumen Docker persistente). El cache sobrevive
entre reinicios del contenedor, así que el primer request de upload puede
tardar 5-15s mientras se baja el modelo y los siguientes son instantáneos.

El singleton se protege con un lock (double-checked) para que el modelo se
cargue UNA sola vez por proceso de uvicorn (los workers lo cargarian
independientemente, pero con --workers 1 el ciclo es 1:1). Con @lru_cache solo
no alcanza: no bloquea, asi que si el warm-up de arranque (F19) y la primera
busqueda RAG llegan a la vez, ambos cargan el modelo (RAM x2 y mas lento).
"""

import logging
import os
import threading

from langchain_community.embeddings import HuggingFaceEmbeddings

logger = logging.getLogger(__name__)


# Nombre del modelo y dimension. Ambos deben matchear schema.sql (vector(384)).
EMBEDDING_MODEL_NAME = "intfloat/multilingual-e5-small"
EMBEDDING_DIM = 384


# Directorio donde HF/sentence-transformers guardan el modelo bajado.
# El backend Dockerfile setea SENTENCE_TRANSFORMERS_HOME=/app/.cache/sentence-transformers.
# Si esa env var no esta seteada (ej: tests locales), usamos HF_HOME.
_CACHE_DIR = os.environ.get(
    "SENTENCE_TRANSFORMERS_HOME",
    os.environ.get("HF_HOME", "/app/.cache/huggingface"),
)


_instance: HuggingFaceEmbeddings | None = None
_load_lock = threading.Lock()


def get_embeddings() -> HuggingFaceEmbeddings:
    """
    Singleton del modelo de embeddings (thread-safe).

    Primer llamado: descarga el modelo si no esta en cache (~80MB, 5-15s).
    Llamados concurrentes durante esa carga esperan a la misma carga en vez de
    iniciar otra. Siguientes llamados: retorna el objeto cached (instantaneo,
    sin tomar el lock). Si la carga falla no se cachea nada: el proximo llamado
    reintenta.

    Returns:
        HuggingFaceEmbeddings listo para .embed_documents() / .embed_query().
    """
    global _instance
    if _instance is None:
        with _load_lock:
            if _instance is None:
                logger.info(
                    "Cargando modelo de embeddings '%s' (cache=%s, dim=%d)",
                    EMBEDDING_MODEL_NAME,
                    _CACHE_DIR,
                    EMBEDDING_DIM,
                )
                _instance = HuggingFaceEmbeddings(
                    model_name=EMBEDDING_MODEL_NAME,
                    cache_folder=_CACHE_DIR,
                    # 'cpu' es explicito aunque es el default. Evita warnings
                    # cuando torch detecta CUDA y queremos forzar CPU.
                    model_kwargs={"device": "cpu"},
                    # normalize=True para que dot product == cosine similarity.
                    # Hace que el scoring sea consistente independientemente de
                    # la magnitud.
                    encode_kwargs={"normalize_embeddings": True},
                )
    return _instance


# --- Warm-up (F19: primera propuesta < 5 min) --------------------------------


def warmup_enabled() -> bool:
    """``EMBEDDINGS_WARMUP`` (default ``on``); ``off``/``0``/``false``/``no`` lo desactiva."""
    value = os.getenv("EMBEDDINGS_WARMUP", "on").strip().lower()
    return value not in {"off", "0", "false", "no"}


def warmup_embeddings() -> bool:
    """Precarga el modelo. Best-effort: nunca lanza (no debe tumbar el arranque).

    Devuelve True si el modelo quedo cargado. Si falla, ``get_embeddings()``
    volvera a intentarlo en la primera busqueda real.
    """
    try:
        get_embeddings()
    except Exception:
        logger.exception("No se pudo precargar el modelo de embeddings")
        return False
    logger.info("Modelo de embeddings precargado")
    return True
