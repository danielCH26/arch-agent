"""
Pruebas del nivel `modulo` y de la cobertura de patrones por tipo de módulo.

Dos cosas que vale la pena fijar con pruebas:

1. **Los patrones de nivel `modulo` no son estilos de arquitectura.** Viven en
   el RAG para el árbol de carpetas. Si se colaran a la propuesta, la tabla de
   trade-offs compararía "Repository" contra "Microservicios", y en un
   proyecto CRUD el retrieval podría poner Repository primero y desplazar al
   estilo real. El filtro en `proposal_generator._eligible` lo evita, y
   `is_non_architectural` es lo que ese filtro consulta.

2. **La auditoría de cobertura está en los datos, no en un documento.** La
   lista de tipos de módulo sin patrón aplicable se CALCULA; acá se compara
   contra `KNOWN_UNCOVERED_MODULE_KINDS`, que está escrita a mano con la razón
   de cada hueco. Si alguien etiqueta un patrón nuevo (o agrega un tipo de
   módulo y se olvida de etiquetarlo), esta prueba falla y obliga a actualizar
   la explicación. Es el objetivo de la tarea de auditoría de la historia.
"""

import pytest

from app.core.convention_catalog import ROLES
from app.core.pattern_catalog import (
    KNOWN_UNCOVERED_MODULE_KINDS,
    NON_ARCHITECTURAL_LEVELS,
    VALID_LEVELS,
    VALID_MODULE_KINDS,
    is_non_architectural,
    load_patterns,
    module_kinds_without_patterns,
    pattern_module_entry,
    patterns_for_module_kind,
)

# Los cuatro patrones de nivel módulo que se agregaron para esta historia.
PATRONES_DE_MODULO = (
    "Repository",
    "Service Layer",
    "Unit of Work",
    "Data Transfer Object (DTO)",
)


class TestCoberturaDeLaAuditoria:
    def test_los_huecos_calculados_coinciden_con_los_documentados(self):
        assert sorted(module_kinds_without_patterns()) == sorted(
            KNOWN_UNCOVERED_MODULE_KINDS
        ), (
            "La cobertura de patrones por tipo de módulo cambió. Actualiza "
            "KNOWN_UNCOVERED_MODULE_KINDS en app/core/pattern_catalog.py con la "
            "razón del hueco, o etiqueta el patrón que falta con "
            "applies_to_modules."
        )

    def test_la_mayoria_de_los_tipos_tiene_cobertura(self):
        cubiertos = len(VALID_MODULE_KINDS) - len(KNOWN_UNCOVERED_MODULE_KINDS)
        assert cubiertos >= len(VALID_MODULE_KINDS) * 0.7

    def test_el_tipo_por_omision_siempre_tiene_patron(self):
        # Si "crud" quedara sin patrón, un módulo que cayó al tipo por omisión
        # no recibiría ninguna propuesta, que es el peor caso posible.
        assert patterns_for_module_kind("crud")

    def test_un_tipo_inventado_no_devuelve_nada(self):
        assert patterns_for_module_kind("no_existe") == []


class TestCatalogoDePatrones:
    def test_todo_patron_declara_applies_to_modules(self):
        faltantes = [
            p["pattern_name"]
            for p in load_patterns()
            if "applies_to_modules" not in p
        ]
        assert not faltantes, (
            f"Estos patrones no declaran applies_to_modules: {faltantes}. "
            "Una lista vacía es una respuesta válida (y hay que comentar por "
            "qué); no declarar el campo no lo es."
        )

    def test_los_niveles_son_validos(self):
        for pattern in load_patterns():
            assert pattern.get("level") in VALID_LEVELS, pattern["pattern_name"]

    @pytest.mark.parametrize("nombre", PATRONES_DE_MODULO)
    def test_los_patrones_nuevos_estan_en_el_catalogo(self, nombre):
        entrada = pattern_module_entry(nombre)
        assert entrada is not None
        assert entrada["level"] == "modulo"
        assert entrada["kinds"], f"{nombre} no aplica a ningún tipo de módulo"
        assert entrada["contributions"], f"{nombre} no aporta nada al árbol"

    @pytest.mark.parametrize("nombre", PATRONES_DE_MODULO)
    def test_los_patrones_nuevos_tienen_fuentes_reales(self, nombre):
        pattern = next(
            p for p in load_patterns() if p["pattern_name"] == nombre
        )
        fuentes = pattern.get("fuentes") or []
        assert fuentes, nombre
        for fuente in fuentes:
            assert fuente.get("titulo")
            assert str(fuente.get("url", "")).startswith("http"), fuente

    @pytest.mark.parametrize("nombre", PATRONES_DE_MODULO)
    def test_los_patrones_nuevos_dicen_cuando_no_usarlos(self, nombre):
        # Sin esto el ADR recomendaría el patrón para todo módulo del tipo, y
        # varios de estos tienen un mal uso muy común (DTO entre capas
        # locales, repositorio que solo reenvía al ORM).
        pattern = next(p for p in load_patterns() if p["pattern_name"] == nombre)
        assert str(pattern.get("when_not_to_use") or "").strip(), nombre
        desventajas = (pattern.get("tradeoffs") or {}).get("desventajas") or []
        assert len(desventajas) >= 3, nombre

    def test_todo_aporte_de_estructura_usa_un_rol_del_vocabulario(self):
        for pattern in load_patterns():
            entrada = pattern_module_entry(pattern["pattern_name"])
            if entrada is None:
                continue
            for aporte in entrada["contributions"]:
                assert aporte["role"] in ROLES, pattern["pattern_name"]

    def test_todo_aporte_de_estructura_tiene_fuente_y_justificacion(self):
        for pattern in load_patterns():
            entrada = pattern_module_entry(pattern["pattern_name"])
            if entrada is None:
                continue
            for aporte in entrada["contributions"]:
                assert aporte["note"], (pattern["pattern_name"], aporte["role"])
                assert aporte["source_url"].startswith("http"), pattern["pattern_name"]

    def test_los_tipos_declarados_estan_en_el_vocabulario(self):
        for pattern in load_patterns():
            for kind in pattern.get("applies_to_modules") or []:
                assert kind in VALID_MODULE_KINDS, (
                    pattern["pattern_name"],
                    kind,
                )


class TestNivelModuloFueraDeLaPropuesta:
    @pytest.mark.parametrize("nombre", PATRONES_DE_MODULO)
    def test_un_patron_de_modulo_no_es_arquitectonico(self, nombre):
        assert is_non_architectural(nombre)

    @pytest.mark.parametrize(
        "nombre",
        [
            "Microservicios",
            "Arquitectura en capas (Layered)",
            "Arquitectura hexagonal (Puertos y Adaptadores)",
        ],
    )
    def test_un_estilo_de_arquitectura_si_es_arquitectonico(self, nombre):
        assert not is_non_architectural(nombre)

    def test_un_patron_desconocido_no_se_filtra(self):
        # Ante la duda se deja pasar: filtrar un patrón que no está en el
        # catálogo lo sacaría de la propuesta sin razón.
        assert not is_non_architectural("Patrón que no existe")
        assert not is_non_architectural(None)

    def test_los_patrones_de_codigo_siguen_disponibles_para_la_propuesta(self):
        # El filtro solo saca `modulo`. Capas, hexagonal, clean y MVC son de
        # nivel `codigo` y deben seguir pudiendo citarse.
        assert "codigo" not in NON_ARCHITECTURAL_LEVELS

    def test_los_patrones_de_modulo_no_aparecen_entre_los_estilos(self):
        estilos = [
            p["pattern_name"]
            for p in load_patterns()
            if p.get("level") != "modulo"
        ]
        for nombre in PATRONES_DE_MODULO:
            assert nombre not in estilos
