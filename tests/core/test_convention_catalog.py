"""
Pruebas del catálogo de convenciones de estructura de repositorio.

Mismo criterio que en `test_cloud_catalog.py`: el catálogo son YAML
versionados en el repo, así que lo que de verdad se puede romper es una
edición a mano. Lo que se cubre acá es eso, y sobre todo una cosa:

**que ninguna línea del árbol pueda llegar a la interfaz o al ADR sin
fuente.** Es el criterio de aceptación de la historia, y la única forma de
garantizarlo es que un YAML con una fuente faltante o con un `source` que
apunta a la nada no cargue.
"""

import textwrap

import pytest

from app.core import convention_catalog
from app.core.convention_catalog import (
    LAYERS,
    ROLES,
    ConventionCatalogError,
    catalog_documents,
    get_convention,
    list_conventions,
    load_catalog,
    match_convention,
    normalize,
)


@pytest.fixture(autouse=True)
def _clean_cache():
    convention_catalog.reset_catalog_cache()
    yield
    convention_catalog.reset_catalog_cache()


def _write(tmp_path, name, body):
    path = tmp_path / name
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return path


VALIDO = """
    convention_id: demo
    name: "Demo"
    layer: backend
    matches: [demo, demo framework]
    weight: 10
    summary: "Una convención de prueba."
    base_tree:
      - path: "src/"
        note: "raíz"
        source: 1
    module_tree:
      - path: "src/{module}.py"
        note: "módulo"
        source: 1
        role: api
    pattern_slot: "src/{role_dir}/{module}.py"
    pattern_slot_source: 1
    documented_roles: [api]
    fuentes:
      - titulo: "Documentación de demo"
        url: "https://example.com/demo"
"""


class TestCatalogoReal:
    """El catálogo que se versiona en data/conventions/."""

    def test_carga_las_cuatro_convenciones(self):
        ids = {c.convention_id for c in list_conventions()}
        assert {"fastapi", "react", "django", "spring_boot"} <= ids

    def test_toda_linea_tiene_fuente(self):
        for convention in list_conventions():
            for node in (*convention.base_tree, *convention.module_tree):
                assert node.source_title, f"{convention.convention_id}: {node.path}"
                assert node.source_url.startswith("http"), node.path

    def test_toda_convencion_tiene_ranura_para_patrones_con_fuente(self):
        for convention in list_conventions():
            assert convention.pattern_slot
            assert convention.pattern_slot_source_url.startswith("http")

    def test_las_capas_son_validas(self):
        for convention in list_conventions():
            assert convention.layer in LAYERS

    def test_los_roles_declarados_estan_en_el_vocabulario(self):
        for convention in list_conventions():
            assert convention.documented_roles <= set(ROLES)

    def test_hay_al_menos_una_convencion_por_capa(self):
        capas = {c.layer for c in list_conventions()}
        assert capas == set(LAYERS)

    def test_el_module_tree_usa_el_marcador_de_modulo(self):
        # Sin `{module}` el árbol daría la misma ruta para todos los módulos y
        # el deduplicado los colapsaría en uno.
        for convention in list_conventions():
            assert any("{module}" in n.path.lower() for n in convention.module_tree), (
                convention.convention_id
            )

    def test_react_declara_el_limite_de_anidamiento_de_su_fuente(self):
        react = get_convention("react")
        assert react.nesting_limit == 4

    def test_spring_documenta_servicio_y_repositorio(self):
        # Es la única cuya fuente oficial ya nombra esos roles; si esto cambia,
        # el árbol empezaría a duplicar carpetas que la convención ya trae.
        spring = get_convention("spring_boot")
        assert {"service", "repository"} <= spring.documented_roles

    def test_genera_un_documento_indexable_por_convencion(self):
        documentos = list(catalog_documents())
        assert len(documentos) == len(list_conventions())
        for _clave, texto, meta in documentos:
            assert texto.strip()
            assert meta["convention_id"]
            assert meta["layer"] in LAYERS
            assert meta["fuentes"]


class TestValidacion:
    def test_un_yaml_valido_carga(self, tmp_path, monkeypatch):
        _write(tmp_path, "demo.yaml", VALIDO)
        monkeypatch.setattr(convention_catalog, "CONVENTIONS_DIR", tmp_path)
        convention_catalog.reset_catalog_cache()
        assert get_convention("demo").name == "Demo"

    @pytest.mark.parametrize(
        "reemplazo, esperado",
        [
            # source que apunta a una fuente que no existe: es EL caso que
            # dejaría una línea del árbol sin respaldo.
            ("source: 1\n        role: api", "source: 9\n        role: api"),
            ('layer: backend', 'layer: middleware'),
            ("role: api", "role: inventado"),
            ("matches: [demo, demo framework]", "matches: []"),
            ("pattern_slot_source: 1", "pattern_slot_source: 7"),
            ("documented_roles: [api]", "documented_roles: [noexiste]"),
        ],
    )
    def test_un_yaml_invalido_no_carga(self, tmp_path, monkeypatch, reemplazo, esperado):
        _write(tmp_path, "demo.yaml", VALIDO.replace(reemplazo, esperado))
        monkeypatch.setattr(convention_catalog, "CONVENTIONS_DIR", tmp_path)
        convention_catalog.reset_catalog_cache()
        assert "demo" not in load_catalog()

    def test_un_archivo_roto_no_tumba_a_los_demas(self, tmp_path, monkeypatch):
        _write(tmp_path, "bueno.yaml", VALIDO)
        _write(tmp_path, "roto.yaml", "convention_id: roto\nlayer: backend\n")
        monkeypatch.setattr(convention_catalog, "CONVENTIONS_DIR", tmp_path)
        convention_catalog.reset_catalog_cache()
        catalogo = load_catalog()
        assert "demo" in catalogo
        assert "roto" not in catalogo

    def test_pedir_una_convencion_inexistente_falla_claro(self):
        # `match` es re.search y es sensible a mayúsculas: el mensaje empieza
        # con "No existe la convención ...".
        with pytest.raises(ConventionCatalogError, match="No existe la convención"):
            get_convention("no_existe")

    def test_directorio_ausente_devuelve_catalogo_vacio(self, tmp_path, monkeypatch):
        monkeypatch.setattr(convention_catalog, "CONVENTIONS_DIR", tmp_path / "nada")
        convention_catalog.reset_catalog_cache()
        assert load_catalog() == {}


class TestMatch:
    def test_reconoce_el_stack_por_la_tecnologia(self):
        convention, termino = match_convention(["FastAPI y PostgreSQL"], layer="backend")
        assert convention is not None
        assert convention.convention_id == "fastapi"
        assert termino == "fastapi"

    def test_gana_el_termino_mas_largo(self):
        # "spring boot" le gana a "spring": si ganara el más corto, un proyecto
        # Spring Boot podría caer en otra convención que también liste "spring".
        convention, termino = match_convention(["Spring Boot 3"], layer="backend")
        assert convention is not None
        assert convention.convention_id == "spring_boot"
        assert termino == "spring boot"

    def test_respeta_la_capa(self):
        convention, _ = match_convention(["React"], layer="backend")
        assert convention is None

    def test_sin_coincidencia_devuelve_none_y_no_adivina(self):
        convention, termino = match_convention(["COBOL sobre AS/400"], layer="backend")
        assert convention is None
        assert termino == ""

    def test_terminos_vacios_devuelven_none(self):
        assert match_convention([], layer="backend") == (None, "")
        assert match_convention(["", None], layer="backend") == (None, "")

    def test_normaliza_tildes_y_mayusculas(self):
        assert normalize("Aplicación WEB") == "aplicacion web"
