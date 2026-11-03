"""
El contrato entre `plan_to_dict` y el modelo de respuesta de la API.

Esto existe por un bug real: se agregó `notes` al plan y al tipo de
TypeScript, pero no a `GenerateOut`. Pydantic descarta en silencio lo que no
está declarado, así que el backend no falla — el campo simplemente no viaja,
llega `undefined` al panel y React revienta allá, lejos de la causa.

Una prueba de un endpoint no lo habría visto (la respuesta es válida). Lo que
hace falta es comparar las dos formas.
"""

import pytest

from app.api import repo_structure as repo_structure_api
from app.api.repo_structure import ATTACHMENT_KIND, GenerateOut
from app.core.repo_structure import build_plan, plan_to_dict

MERMAID = """graph TD
    UI[Interfaz web] --> API[API REST]
    API --> PED[Gestion de pedidos]
"""
PROPUESTA = "## Tecnologias\n- **Backend**: FastAPI\n- **Frontend**: React\n"


@pytest.fixture
def payload():
    return plan_to_dict(build_plan(mermaid=MERMAID, proposal_markdown=PROPUESTA))


def test_el_modelo_declara_todo_lo_que_produce_el_plan(payload):
    declarados = set(GenerateOut.model_fields)
    producidos = set(payload)
    faltantes = producidos - declarados
    assert not faltantes, (
        f"`plan_to_dict` produce {sorted(faltantes)} pero GenerateOut no lo "
        "declara. Pydantic lo descarta en silencio y el panel recibe "
        "`undefined`."
    )


def test_el_modelo_no_declara_campos_que_el_plan_no_produce(payload):
    # `attachment_id` lo agrega el endpoint, no el plan.
    declarados = set(GenerateOut.model_fields) - {"attachment_id"}
    sobrantes = declarados - set(payload)
    assert not sobrantes, (
        f"GenerateOut declara {sorted(sobrantes)} pero el plan no lo produce: "
        "el panel recibiría siempre el valor por omisión."
    )


def test_la_respuesta_conserva_las_aclaraciones():
    """El caso concreto que falló: un proyecto Django trae `notes`."""
    plan = plan_to_dict(
        build_plan(
            mermaid="graph TD\n  FE[Frontend Web] --> API[API REST]",
            tecnologias=["Django 4.x"],
        )
    )
    assert plan["notes"], "el plan debería traer la aclaración de las plantillas"
    respuesta = GenerateOut(attachment_id="x", **plan)
    assert respuesta.notes == plan["notes"]


def test_la_respuesta_conserva_las_listas_que_usa_el_panel(payload):
    respuesta = GenerateOut(attachment_id="x", **payload)
    assert respuesta.lines == payload["lines"]
    assert respuesta.modules == payload["modules"]
    assert respuesta.tree_text == payload["tree_text"]


class TestLaEstructuraCorrespondeALaArquitecturaVigente:
    """El ADR no puede mostrar un árbol armado sobre un diagrama anterior.

    El despliegue ya filtraba por `architecture_attachment_id`; la estructura
    no. Entonces, si el usuario aprobaba un diagrama nuevo y no volvía a
    generar la estructura, el ADR salía con el árbol del diagrama viejo —
    callado, que es lo peor.
    """

    @staticmethod
    def _att(att_id: str, arquitectura, plan=None):
        att = {
            "id": att_id,
            "kind": ATTACHMENT_KIND,
            "plan": plan or {"tree_text": f"arbol-{att_id}"},
        }
        if arquitectura is not None:
            att["architecture_attachment_id"] = arquitectura
        return att

    @pytest.fixture
    def leer(self, monkeypatch):
        estado: dict = {"filas": []}

        monkeypatch.setattr(
            repo_structure_api,
            "_structure_rows",
            lambda db, **kw: estado["filas"] if kw.get("offset", 0) == 0 else [],
        )

        def _leer(arquitectura=None):
            return repo_structure_api.latest_structure_plan(
                None, user_id=1, project_id=1, architecture_attachment_id=arquitectura
            )

        return estado, _leer

    def test_descarta_la_estructura_de_la_arquitectura_anterior(self, leer):
        estado, _leer = leer
        estado["filas"] = [(1, None, [self._att("est-v1", "arq-v1")])]
        assert _leer("arq-v2") is None

    def test_devuelve_la_de_la_arquitectura_vigente(self, leer):
        estado, _leer = leer
        estado["filas"] = [(1, None, [self._att("est-v2", "arq-v2")])]
        assert _leer("arq-v2")["tree_text"] == "arbol-est-v2"

    def test_se_salta_la_vieja_y_encuentra_la_que_corresponde(self, leer):
        estado, _leer = leer
        # Más reciente primero, como las devuelve la consulta.
        estado["filas"] = [
            (2, None, [self._att("est-v1", "arq-v1")]),
            (1, None, [self._att("est-v2", "arq-v2")]),
        ]
        assert _leer("arq-v2")["tree_text"] == "arbol-est-v2"

    def test_una_estructura_vieja_sin_el_dato_se_acepta(self, leer):
        # Mismo criterio que el despliegue: descartarla dejaría sin sección a
        # los ADR ya generados.
        estado, _leer = leer
        estado["filas"] = [(1, None, [self._att("est-vieja", None)])]
        assert _leer("arq-v2") is not None

    def test_sin_arquitectura_conocida_se_acepta_cualquiera(self, leer):
        estado, _leer = leer
        estado["filas"] = [(1, None, [self._att("est-v1", "arq-v1")])]
        assert _leer(None) is not None


class TestElCatalogoDelArbolSaleDelYaml:
    """El árbol se compone desde el YAML, no desde el RAG, y hay que decirlo.

    La tabla `repo_convention_chunks` existe porque la historia pide que las
    convenciones estén indexadas, pero NINGÚN código la consulta para armar el
    árbol: la composición es determinista y necesita los campos exactos, no el
    vecino más cercano de una búsqueda por similitud.

    Esta prueba compara las dos fuentes para que no se separen.
    """

    def test_el_texto_que_se_indexa_sale_del_mismo_catalogo(self):
        from app.core.convention_catalog import catalog_documents, list_conventions

        indexadas = {meta["convention_id"] for _k, _t, meta in catalog_documents()}
        assert indexadas == {c.convention_id for c in list_conventions()}

    def test_cada_documento_indexado_nombra_su_convencion_y_sus_fuentes(self):
        from app.core.convention_catalog import catalog_documents, get_convention

        for _clave, texto, meta in catalog_documents():
            convention = get_convention(meta["convention_id"])
            assert convention.name in texto
            assert meta["fuentes"] == [dict(f) for f in convention.fuentes]

    def test_componer_el_arbol_no_toca_la_base(self):
        """La propiedad de verdad detrás de «sale del YAML, no del RAG».

        Un docstring puede volver a mentir; esto no. Si alguien hace que la
        composición consulte la base, este import aparece y la prueba falla.

        (Probar el texto del docstring fue tentador y es frágil: se rompe por
        una mayúscula o porque la frase vieja se cita para explicarla.)
        """
        import ast
        import inspect

        from app.core import repo_structure

        arbol = ast.parse(inspect.getsource(repo_structure))
        importados: set[str] = set()
        for nodo in ast.walk(arbol):
            if isinstance(nodo, ast.ImportFrom) and nodo.module:
                importados.add(nodo.module)
            elif isinstance(nodo, ast.Import):
                importados.update(alias.name for alias in nodo.names)

        prohibidos = {
            modulo
            for modulo in importados
            if modulo.startswith(("app.core.rag", "app.core.database", "app.models"))
            or modulo in {"sqlalchemy", "psycopg2"}
        }
        assert not prohibidos, (
            f"La composición del árbol importa {sorted(prohibidos)}: deja de ser "
            "determinista sobre el YAML."
        )

    def test_el_catalogo_de_convenciones_tampoco_toca_la_base(self):
        import ast
        import inspect

        from app.core import convention_catalog

        arbol = ast.parse(inspect.getsource(convention_catalog))
        importados: set[str] = set()
        for nodo in ast.walk(arbol):
            if isinstance(nodo, ast.ImportFrom) and nodo.module:
                importados.add(nodo.module)
            elif isinstance(nodo, ast.Import):
                importados.update(alias.name for alias in nodo.names)
        assert not any(m.startswith(("app.core.database", "app.models")) for m in importados)
