"""
Embeddings wrapper (HU13 stub).

Issue: #8 - HU13

Para HU13, solo necesitamos un stub que devuelva embeddings dummy
para testing. La implementación real del sistema de embeddings es
parte de F08 (Generación de propuesta).

En producción, este módulo debe integrarse con:
- multilingual-e5-small (384d) para embeddings de documentos
- langchain.embeddings.HuggingFaceEmbeddings
"""

from functools import lru_cache
from typing import List


@lru_cache(maxsize=1)
def get_embeddings():
    """
    Singleton de embeddings.

    Por ahora retorna un wrapper con .embed_documents() que devuelve
    embeddings dummy. La implementación real se hará en F08.
    """
    return _DummyEmbeddings()


class _DummyEmbeddings:
    """Embeddings dummy para testing HU13."""

    def __init__(self, dim: int = 384):
        self.dim = dim

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """Retorna embeddings dummy (todos 0.1)."""
        return [[0.1] * self.dim for _ in texts]

    def embed_query(self, text: str) -> List[float]:
        """Retorna un embedding dummy."""
        return [0.1] * self.dim
