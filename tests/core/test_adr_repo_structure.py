"""
La estructura del repositorio dentro del ADR.

La subsección va bajo "4. Diagrama de arquitectura" y NO como sección
numerada propia, por la misma razón que el despliegue: hay código que busca
las secciones por número (``extract_guide_section`` con "## 7.", los saltos
de página del PDF, el lint de la guía). Una sección 5 obligaría a renumerar
todo eso.

Lo que se cubre: que cada decisión salga con su fuente, que lo que no se pudo
decidir se diga, y que un proyecto sin estructura generada no cambie el ADR.
"""

import re

import pytest

from app.core.adr_generator import AdrContext, _repo_structure_block
from app.core.repo_structure import build_plan, plan_to_dict

MERMAID = """graph TD
    UI[Interfaz web] --> API[API REST]
    API --> PED[Gestion de pedidos]
    API --> NOTI[Notificaciones por correo]
"""

PROPUESTA = """## Tecnologias
- **Backend**: FastAPI
- **Frontend**: React
"""


def _celdas(fila: str) -> list[str]:
    """Las celdas de una fila de tabla markdown.

    Separa SOLO por tuberías sin escapar: ``_cell`` escapa las que vienen en
    el texto (``Pedidos \\| ventas``), y partir por todas daría una columna de
    más donde el markdown renderiza bien.
    """
    return [celda.strip() for celda in re.split(r"(?<!\\)\|", fila.strip())[1:-1]]


def _filas(bloque: str) -> list[str]:
    return [
        linea
        for linea in bloque.splitlines()
        if linea.startswith("| ") and "---" not in linea and "Módulo |" not in linea
    ]


def _ctx(repo_structure=None) -> AdrContext:
    return AdrContext(
        project_name="Proyecto de prueba",
        project_description="",
        current_phase="revision",
        repo_structure=repo_structure,
    )


@pytest.fixture
def plan():
    return plan_to_dict(build_plan(mermaid=MERMAID, proposal_markdown=PROPUESTA))


class TestSinEstructura:
    @pytest.mark.parametrize("valor", [None, {}, "texto", [], {"tree_text": ""}])
    def test_sin_plan_la_seccion_no_aparece(self, valor):
        assert _repo_structure_block(_ctx(valor)) == ""


class TestConEstructura:
    def test_es_una_subseccion_y_no_una_seccion_numerada(self, plan):
        bloque = _repo_structure_block(_ctx(plan))
        assert "### Estructura del repositorio" in bloque
        # Ni "## 5." ni ningún encabezado de nivel 2: renumeraría el ADR.
        assert "\n## " not in bloque

    def test_trae_el_arbol_en_un_bloque_de_codigo(self, plan):
        bloque = _repo_structure_block(_ctx(plan))
        assert "```" in bloque
        assert "app/" in bloque
        assert "routers/" in bloque

    def test_hay_una_linea_en_blanco_antes_del_bloque_de_codigo(self, plan):
        """Sin ella, el PDF salía con el árbol en un renglón.

        El renderer del ADR consume un párrafo hasta encontrar una línea
        vacía. Si el ``` viene pegado al párrafo anterior, se lo traga junto
        con todo el árbol y lo imprime en una sola línea, con los backticks a
        la vista y sin la indentación de las carpetas.
        """
        bloque = _repo_structure_block(_ctx(plan))
        lineas = bloque.splitlines()
        apertura = next(i for i, l in enumerate(lineas) if l.strip() == "```")
        assert apertura > 0
        assert lineas[apertura - 1].strip() == "", (
            "El bloque de código necesita una línea en blanco antes: "
            f"lo precede {lineas[apertura - 1]!r}"
        )

    def test_el_arbol_no_trae_marcadores_sin_reemplazar(self, plan):
        bloque = _repo_structure_block(_ctx(plan))
        assert "{module}" not in bloque
        assert "{role_dir}" not in bloque

    def test_nombra_las_convenciones_y_el_termino_que_las_activo(self, plan):
        bloque = _repo_structure_block(_ctx(plan))
        assert "FastAPI" in bloque
        assert "React" in bloque
        assert "fastapi" in bloque  # el término que la reconoció

    def test_la_tabla_trae_patron_ubicacion_razon_y_fuente(self, plan):
        """Cinco columnas, no seis: la razón y la fuente van juntas.

        Con seis, la tabla se desbordaba del ancho de la página en el PDF y la
        última —la fuente— salía cortada a media palabra. Justo la columna que
        sostiene el criterio de aceptación.
        """
        bloque = _repo_structure_block(_ctx(plan))
        assert (
            "| Módulo | Tipo | Patrón | Dónde queda | Por qué y de dónde sale |"
            in bloque
        )
        assert "Repository" in bloque
        assert "Martin Fowler" in bloque or "Microsoft Learn" in bloque

    def test_toda_fila_de_la_tabla_trae_una_fuente(self, plan):
        bloque = _repo_structure_block(_ctx(plan))
        filas = _filas(bloque)
        assert filas
        for fila in filas:
            celdas = _celdas(fila)
            assert len(celdas) == 5, fila
            # La fuente va al final de la última celda, junto a la razón.
            assert "Fuente:" in celdas[-1], f"fila sin fuente: {fila}"
            fuente = celdas[-1].split("Fuente:")[-1].strip(" .")
            assert fuente and fuente != "—", f"fila con fuente vacía: {fila}"

    def test_dice_que_modulos_quedaron_sin_patron(self, plan):
        bloque = _repo_structure_block(_ctx(plan))
        assert "Notificaciones por correo" in bloque
        assert "no tiene hoy ninguno" in bloque

    def test_no_repite_el_aviso_de_modulo_sin_patron(self, plan):
        """Salía dos veces: en su párrafo y otra vez en "Pendientes"."""
        bloque = _repo_structure_block(_ctx(plan))
        assert bloque.count("ningún patrón declarado aplicable") <= 1

    def test_una_tuberia_en_un_nombre_no_rompe_la_tabla(self):
        plan = plan_to_dict(
            build_plan(
                mermaid="graph TD\n  A[Gestion de pedidos | ventas]",
                proposal_markdown=PROPUESTA,
            )
        )
        bloque = _repo_structure_block(_ctx(plan))
        filas = _filas(bloque)
        assert filas
        for fila in filas:
            # La tubería del nombre llega escapada, así que la tabla sigue
            # teniendo cinco columnas.
            assert "\\|" in fila
            assert len(_celdas(fila)) == 5, fila
