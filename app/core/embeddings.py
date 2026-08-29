"""
Embeddings wrapper para HU13 (issue #8).

Modelo: intfloat/multilingual-e5-small (384 dimensiones).

El modelo se baja de HuggingFace la primera vez (~80MB) y queda cacheado en
`/app/.cache/huggingface` (volumen Docker persistente). El cache sobrevive
entre reinicios del contenedor, así que el primer request de upload puede
tardar 5-15s mientras se baja el modelo y los siguientes son instantáneos.

El singleton esta decorado con @lru_cache(maxsize=1) para que el modelo se
cargue UNA sola vez por proceso de uvicorn (los workers lo cargarian
independientemente, pero con --workers 1 el ciclo es 1:1).
"""

from functools import lru_cache
import logging
import os

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


@lru_cache(maxsize=1)
def get_embeddings() -> HuggingFaceEmbeddings:
    """
    Singleton del modelo de embeddings.

    Primer llamado: descarga el modelo si no esta en cache (~80MB, 5-15s).
    Siguientes llamados: retorna el objeto cached (instantaneo).

    Returns:
        HuggingFaceEmbeddings listo para .embed_documents() / .embed_query().
    """
    logger.info(
        "Cargando modelo de embeddings '%s' (cache=%s, dim=%d)",
        EMBEDDING_MODEL_NAME,
        _CACHE_DIR,
        EMBEDDING_DIM,
    )
    return HuggingFaceEmbeddings(
        model_name=EMBEDDING_MODEL_NAME,
        cache_folder=_CACHE_DIR,
        # 'cpu' es explicito aunque es el default. Evita warnings cuando
        # torch detecta CUDA y queremos forzar CPU.
        model_kwargs={"device": "cpu"},
        # normalize=True para que dot product == cosine similarity.
        # Hace que el scoring sea consistente independientemente de la magnitud.
        encode_kwargs={"normalize_embeddings": True},
    )