"""
Pruebas del catálogo de servicios de nube.

El catálogo son dos YAML versionados en el repo: lo que puede romperse es
una edición a mano (un ícono que falta, una categoría mal escrita, un
`connects_to` que apunta a un servicio que ya no existe). Estas pruebas
cubren exactamente eso.
"""

import textwrap

import pytest

from app.core import cloud_catalog
from app.core.cloud_catalog import (
    CATEGORIES,
    CloudCatalogError,
    catalog_documents,
    get_provider,
    list_providers,
    load_catalog,
    missing_icons,
    normalize,
)


@pytest.fixture(autouse=True)
def _clean_cache():
    cloud_catalog.reset_catalog_cache()
    yield
    cloud_catalog.reset_catalog_cache()


# --------------------------------------------------------------------------
# El catálogo real del repo
# --------------------------------------------------------------------------


def test_carga_los_dos_proveedores_de_la_demo():
    providers = {p.id for p in list_providers()}
    assert {"aws", "gcp"} <= providers


def test_cada_servicio_tiene_su_icono():
    """Un servicio sin PNG sale con un glifo gris en el diagrama. Es un
    fallback deliberado, pero el catálogo del repo no debería necesitarlo."""
    assert missing_icons() == []


def test_todas_las_categorias_son_conocidas():
    for provider in list_providers():
        for service in provider.services:
            assert service.category in CATEGORIES, (
                f"{provider.id}/{service.id} usa la categoría "
                f"'{service.category}', que no está registrada"
            )


def test_las_dos_nubes_cubren_las_mismas_categorias_basicas():
    """El criterio de aceptación pide que funcione para cada nube soportada:
    si una no tiene base de datos o cómputo, un proyecto normal quedaría a
    medias al cambiar de proveedor."""
    basicas = {"compute", "database", "storage", "queue", "cdn", "auth", "monitoring"}
    for provider in list_providers():
        presentes = {s.category for s in provider.services}
        assert basicas <= presentes, (
            f"{provider.id} no cubre: {sorted(basicas - presentes)}"
        )


def test_cada_servicio_dice_donde_desplegarse():
    """`deploy_note` es lo que alimenta la columna "Cómo desplegarlo" de la
    interfaz; un servicio sin esa nota deja la tabla coja."""
    for provider in list_providers():
        for service in provider.services:
            assert service.deploy_note.strip(), f"{provider.id}/{service.id} sin deploy_note"


def test_los_documentos_para_el_rag_salen_uno_por_servicio():
    documentos = list(catalog_documents())
    total = sum(len(p.services) for p in list_providers())
    assert len(documentos) == total
    _key, texto, meta = documentos[0]
    assert meta["source"] == "cloud_catalog"
    assert meta["provider"] in {"aws", "gcp"}
    assert texto.strip()


def test_proveedor_desconocido_lanza_con_las_opciones():
    with pytest.raises(CloudCatalogError) as excinfo:
        get_provider("azure")
    assert "azure" in str(excinfo.value)
    # El mensaje tiene que decir cuáles SÍ hay, no solo que falló.
    assert "aws" in str(excinfo.value)


def test_el_proveedor_se_resuelve_sin_importar_mayusculas():
    assert get_provider("AWS").id == "aws"
    assert get_provider("  gcp  ").id == "gcp"


# --------------------------------------------------------------------------
# Normalización
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "entrada,esperado",
    [
        ("Autenticación", "autenticacion"),
        ("Base de Datos (PostgreSQL)", "base de datos postgresql"),
        ("API-Gateway", "api gateway"),
        ("  Caché   Redis  ", "cache redis"),
        ("", ""),
    ],
)
def test_normalize(entrada, esperado):
    assert normalize(entrada) == esperado


# --------------------------------------------------------------------------
# Validación al cargar
# --------------------------------------------------------------------------


def _escribir_catalogo(tmp_path, monkeypatch, contenido: str):
    carpeta = tmp_path / "cloud"
    carpeta.mkdir()
    (carpeta / "test.yaml").write_text(textwrap.dedent(contenido), encoding="utf-8")
    monkeypatch.setattr(cloud_catalog, "CLOUD_DATA_DIR", carpeta)
    cloud_catalog.reset_catalog_cache()


_BASE = """
    id: demo
    name: Demo Cloud
    tiers:
      - id: compute
        label: Cómputo
    services:
      - id: vm
        name: Demo VM
        category: compute
        tier: compute
        matches: [servidor]
        connects_to: []
"""


def test_un_catalogo_minimo_valido_carga(tmp_path, monkeypatch):
    _escribir_catalogo(tmp_path, monkeypatch, _BASE)
    assert get_provider("demo").service("vm").name == "Demo VM"


def test_connects_to_hacia_un_servicio_inexistente_descarta_el_archivo(
    tmp_path, monkeypatch
):
    """Una flecha hacia un servicio que no existe dibujaría una conexión a
    ninguna parte. Se detecta al cargar, no en mitad de un render."""
    roto = _BASE.replace("connects_to: []", "connects_to: [fantasma]")
    _escribir_catalogo(tmp_path, monkeypatch, roto)
    with pytest.raises(CloudCatalogError):
        load_catalog()


def test_categoria_desconocida_descarta_el_archivo(tmp_path, monkeypatch):
    roto = _BASE.replace("category: compute", "category: cuantica")
    _escribir_catalogo(tmp_path, monkeypatch, roto)
    with pytest.raises(CloudCatalogError):
        load_catalog()


def test_un_tier_no_declarado_descarta_el_archivo(tmp_path, monkeypatch):
    roto = _BASE.replace("tier: compute", "tier: inventado")
    _escribir_catalogo(tmp_path, monkeypatch, roto)
    with pytest.raises(CloudCatalogError):
        load_catalog()


def test_un_archivo_roto_no_tumba_a_los_demas(tmp_path, monkeypatch):
    """Un error de edición en gcp.yaml no puede dejar la demo sin AWS."""
    carpeta = tmp_path / "cloud"
    carpeta.mkdir()
    (carpeta / "bueno.yaml").write_text(textwrap.dedent(_BASE), encoding="utf-8")
    (carpeta / "roto.yaml").write_text("id: roto\nname: Roto\n", encoding="utf-8")
    monkeypatch.setattr(cloud_catalog, "CLOUD_DATA_DIR", carpeta)
    cloud_catalog.reset_catalog_cache()

    providers = load_catalog()
    assert "demo" in providers
    assert "roto" not in providers
