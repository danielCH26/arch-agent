"""
Contrato del umbral de relevancia del RAG.

``RAG_MIN_SIMILARITY`` es un contrato de negocio, no un numero de tuning. Vive
en un solo lugar (``app/core/rag_config.py``) y hoy lo usa solo el chat: la
fase de propuesta trae los ``PROPOSAL_RAG_TOP_N`` patrones mas cercanos sin
piso fijo (ver ``PROPOSAL_RAG_MIN_SIMILARITY`` en proposal_generator y
``TestRAGConstants`` en tests/api/test_proposals.py). Estos tests fijan que el
valor no se mueva por accidente y que nadie lo vuelva a declarar.
"""

import inspect
import re

from app.core.rag_config import RAG_MIN_SIMILARITY


def test_el_umbral_sigue_siendo_085():
    assert RAG_MIN_SIMILARITY == 0.85


def test_rag_config_es_el_unico_lugar_de_definicion():
    """Ningun modulo puede volver a declarar la constante.

    Se mira el codigo fuente: si alguno vuelve a asignar
    ``RAG_MIN_SIMILARITY = <numero>``, aparecen dos umbrales que se
    desincronizan en silencio.
    """
    import app.api.chat as chat_module
    import app.api.proposals as proposals_module
    import app.core.proposal_generator as generator_module
    import app.core.rag_config as rag_config_module

    assert "RAG_MIN_SIMILARITY: float = 0.85" in inspect.getsource(rag_config_module)
    for modulo in (chat_module, proposals_module, generator_module):
        # Regex anclada: PROPOSAL_RAG_MIN_SIMILARITY (el piso opcional de la
        # fase de propuesta) es otra variable y no cuenta.
        redeclara = re.search(r"^\s*RAG_MIN_SIMILARITY\s*[:=]", inspect.getsource(modulo), re.M)
        assert redeclara is None, (
            f"{modulo.__name__} re-declara RAG_MIN_SIMILARITY; "
            "el unico lugar de definicion es app/core/rag_config.py"
        )


def test_el_chat_usa_la_constante_compartida():
    """No alcanza con que el valor coincida: debe ser el mismo objeto."""
    from app.api import chat as chat_module

    assert "from app.core.rag_config import RAG_MIN_SIMILARITY" in inspect.getsource(chat_module)
    assert chat_module.RAG_MIN_SIMILARITY is RAG_MIN_SIMILARITY


def test_el_umbral_realmente_filtra_en_el_chat():
    from langchain_core.documents import Document

    from app.api.chat import _is_relevant

    assert _is_relevant(Document(page_content="x", metadata={"similarity": 0.90})) is True
    assert _is_relevant(Document(page_content="x", metadata={"similarity": 0.85})) is True
    assert _is_relevant(Document(page_content="x", metadata={"similarity": 0.70})) is False
