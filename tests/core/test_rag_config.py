"""
Contrato del umbral de relevancia del RAG.

``RAG_MIN_SIMILARITY`` es un contrato de negocio, no un numero de tuning:
bajarlo cambia que citas llegan al modelo en el chat, en la generacion de
propuestas y en las regeneraciones, todo a la vez. Antes de estos fixes vivia
duplicado en tres modulos; estos tests fijan que exista UN solo lugar de
definicion y que ese valor no se mueva por accidente.
"""

from app.core.rag_config import RAG_MIN_SIMILARITY


def test_el_umbral_sigue_siendo_085():
    assert RAG_MIN_SIMILARITY == 0.85


def test_rag_config_es_el_unico_lugar_de_definicion():
    """Ningun consumidor puede volver a declarar la constante.

    Se mira el codigo fuente de cada modulo: si alguno vuelve a asignar
    ``RAG_MIN_SIMILARITY = <numero>``, el retrieval se desincroniza en
    silencio entre el chat y las propuestas.
    """
    import inspect

    import app.api.chat as chat_module
    import app.api.proposals as proposals_module
    import app.core.proposal_generator as generator_module
    import app.core.rag_config as rag_config_module

    # La definicion canonica vive en rag_config.
    fuente_canonica = inspect.getsource(rag_config_module)
    assert "RAG_MIN_SIMILARITY: float = 0.85" in fuente_canonica

    for modulo in (chat_module, proposals_module, generator_module):
        fuente = inspect.getsource(modulo)
        # Solo se admite la forma "from app.core.rag_config import RAG_MIN_SIMILARITY".
        assert "RAG_MIN_SIMILARITY =" not in fuente, (
            f"{modulo.__name__} re-declara RAG_MIN_SIMILARITY; "
            "el unico lugar de definicion es app/core/rag_config.py"
        )
        assert "from app.core.rag_config import RAG_MIN_SIMILARITY" in fuente


def test_los_tres_consumidores_ven_el_mismo_objeto():
    """No alcanza con que los valores coincidan: deben ser la misma constante.

    Si un modulo re-exporta una copia, el test de igualdad de valores seguiria
    en verde y la desincronizacion volveria a colarse.
    """
    from app.api import chat as chat_module
    from app.api import proposals as proposals_module
    from app.core import proposal_generator as generator_module

    assert chat_module.RAG_MIN_SIMILARITY is RAG_MIN_SIMILARITY
    assert proposals_module.RAG_MIN_SIMILARITY is RAG_MIN_SIMILARITY
    assert generator_module.RAG_MIN_SIMILARITY is RAG_MIN_SIMILARITY


def test_el_umbral_realmente_filtra_en_todos_los_consumidores():
    """Cada consumidor aplica el umbral importado, no uno local."""
    from langchain_core.documents import Document

    from app.api.chat import _is_relevant as chat_relevante
    from app.core.proposal_generator import _is_relevant as proposal_relevante

    arriba = Document(page_content="x", metadata={"similarity": 0.90})
    abajo = Document(page_content="x", metadata={"similarity": 0.70})
    justo = Document(page_content="x", metadata={"similarity": 0.85})

    for filtrar in (chat_relevante, proposal_relevante):
        assert filtrar(arriba) is True
        assert filtrar(justo) is True
        assert filtrar(abajo) is False
