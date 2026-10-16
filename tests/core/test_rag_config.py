"""
Contrato del umbral de relevancia del RAG.

``RAG_MIN_SIMILARITY`` es un contrato de negocio, no un numero de tuning:
bajarlo cambia que citas llegan al modelo en el chat. Antes de estos fixes
vivia duplicado en tres modulos; estos tests fijan que exista UN solo lugar de
definicion y que ese valor no se mueva por accidente. La fase de propuesta no
usa este piso (trae los top-N patrones, ver tests/core/test_proposal_generator.py).
"""

import ast
from pathlib import Path

from app.core.rag_config import RAG_MIN_SIMILARITY

APP_DIR = Path(__file__).resolve().parents[2] / "app"


def test_el_umbral_sigue_siendo_085():
    assert RAG_MIN_SIMILARITY == 0.85


def _asignaciones_de(nombre: str, arbol: ast.AST) -> list[int]:
    """Lineas donde ``nombre`` es target de un ``Assign`` o ``AnnAssign``."""
    lineas = []
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Assign):
            targets = nodo.targets
        elif isinstance(nodo, ast.AnnAssign):
            targets = [nodo.target]
        else:
            continue
        for target in targets:
            for sub in ast.walk(target):
                if isinstance(sub, ast.Name) and sub.id == nombre:
                    lineas.append(nodo.lineno)
    return lineas


def test_rag_config_es_el_unico_lugar_de_definicion():
    """Ningun modulo de ``app/`` puede volver a declarar la constante.

    Se parsea con ``ast`` todo ``app/`` (no una lista fija de consumidores):
    cualquier ``RAG_MIN_SIMILARITY = ...`` o ``RAG_MIN_SIMILARITY: float = ...``
    fuera de ``rag_config.py`` vuelve a crear una segunda fuente de verdad para
    el umbral.
    """
    canonico = APP_DIR / "core" / "rag_config.py"
    redeclaraciones = []
    definiciones_canonicas = 0

    for path in sorted(APP_DIR.rglob("*.py")):
        arbol = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        lineas = _asignaciones_de("RAG_MIN_SIMILARITY", arbol)
        if path == canonico:
            definiciones_canonicas = len(lineas)
        else:
            redeclaraciones += [f"{path.relative_to(APP_DIR.parent)}:{n}" for n in lineas]

    assert definiciones_canonicas == 1
    assert redeclaraciones == [], (
        "RAG_MIN_SIMILARITY se re-declara fuera de app/core/rag_config.py: "
        + ", ".join(redeclaraciones)
    )


def test_el_guard_detecta_la_forma_anotada():
    """El guard tiene que ver tambien ``RAG_MIN_SIMILARITY: float = 0.9``."""
    arbol = ast.parse("RAG_MIN_SIMILARITY: float = 0.9\nRAG_MIN_SIMILARITY = 0.8\n")
    assert _asignaciones_de("RAG_MIN_SIMILARITY", arbol) == [1, 2]


def test_el_chat_usa_el_objeto_de_rag_config():
    """No alcanza con que el valor coincida: debe ser la misma constante.

    Si el chat vuelve a tener una copia local, un test de igualdad de valores
    seguiria en verde y la desincronizacion volveria a colarse.
    """
    from app.api import chat as chat_module

    assert chat_module.RAG_MIN_SIMILARITY is RAG_MIN_SIMILARITY


def test_el_umbral_realmente_filtra_en_el_chat():
    """El filtro del chat aplica el umbral importado, no uno local."""
    from langchain_core.documents import Document

    from app.api.chat import _is_relevant

    arriba = Document(page_content="x", metadata={"similarity": 0.90})
    abajo = Document(page_content="x", metadata={"similarity": 0.70})
    justo = Document(page_content="x", metadata={"similarity": 0.85})

    assert _is_relevant(arriba) is True
    assert _is_relevant(justo) is True
    assert _is_relevant(abajo) is False
