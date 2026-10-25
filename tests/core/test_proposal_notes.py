"""Aviso de cambios no pedidos al modificar la propuesta (app/core/proposal_notes.py)."""

from __future__ import annotations

from app.core.proposal_notes import (
    NOTE_TITLE,
    modification_warnings,
    strip_modification_note,
    with_modification_note,
)

PRIOR = """## Componentes
- Pipeline ETL nocturno

## Tecnologias
| Tecnología | Justificación | Requisito que lo motiva |
| --- | --- | --- |
| Python | Equipo | Habilidades |
| Azure Data Factory | Orquesta | Carga nocturna |
| Power BI | Tableros | Tableros |

## Patrones
- Patrón principal: Pipeline de datos ETL / ELT por lotes [1]

## Trade-offs y decisión
- Recomendación: Pipeline de datos ETL / ELT por lotes
- Punto de decisión: ¿Aprueba los trade-offs?
"""


def _new(primary="Pipeline de datos ETL / ELT por lotes [1]", drop="", recommendation=None):
    text = PRIOR.replace("Pipeline de datos ETL / ELT por lotes [1]", primary)
    if drop:
        text = text.replace(drop, "")
    if recommendation:
        text = text.replace("- Recomendación: Pipeline de datos ETL / ELT por lotes", f"- Recomendación: {recommendation}")
    return text


def test_un_ajuste_que_no_nombra_el_patron_y_lo_cambia_se_avisa():
    """Caso real: la iteración 3 no nombró el ETL y volvió Monolito modular."""
    new = _new(primary="Monolito modular (Modular Monolith) [1]", recommendation="Monolito modular")
    warnings = modification_warnings(PRIOR, new, "Agrega el reporte SNIES")
    assert any("cambió de «Pipeline de datos ETL / ELT por lotes» a «Monolito modular" in w for w in warnings)


def test_si_el_comentario_pide_el_cambio_no_se_avisa():
    new = _new(primary="Monolito modular (Modular Monolith) [1]", recommendation="Monolito modular")
    assert modification_warnings(PRIOR, new, "Cambia a un monolito modular") == []


def test_la_misma_arquitectura_escrita_distinto_no_es_un_cambio():
    new = _new(primary="Pipeline ETL/ELT por lotes [1]")
    assert modification_warnings(PRIOR, new, "Agrega el reporte SNIES") == []


def test_una_tecnologia_que_desaparece_sin_pedirlo_se_avisa():
    new = _new(drop="| Azure Data Factory | Orquesta | Carga nocturna |\n")
    warnings = modification_warnings(PRIOR, new, "Agrega el reporte SNIES")
    assert warnings == [
        "Ya no aparecen tecnologías que estaban en la versión anterior y tu comentario no pidió "
        "quitar: Azure Data Factory."
    ]


def test_quitarla_a_pedido_no_se_avisa():
    new = _new(drop="| Azure Data Factory | Orquesta | Carga nocturna |\n")
    assert modification_warnings(PRIOR, new, "Quita Azure Data Factory, usa un cron") == []


def test_recomendacion_distinta_del_patron_principal_se_avisa():
    new = _new(recommendation="Serverless (Function-as-a-Service)")
    warnings = modification_warnings(PRIOR, new, "Ajusta los costos")
    assert any("el documento se contradice" in w for w in warnings)


def test_el_aviso_va_arriba_y_se_puede_quitar():
    noted = with_modification_note(PRIOR, ["Algo cambió"])
    assert noted.startswith(NOTE_TITLE)
    assert "- Algo cambió" in noted
    assert strip_modification_note(noted) == PRIOR
    assert with_modification_note(PRIOR, []) == PRIOR
    # Volver a poner el aviso no lo duplica.
    assert with_modification_note(noted, ["Otra"]).count(NOTE_TITLE) == 1


def test_sin_version_anterior_no_hay_avisos():
    assert modification_warnings(None, PRIOR, "x") == []


def test_el_adr_no_copia_el_aviso():
    from app.core.adr_generator import strip_ui_leftovers

    noted = with_modification_note(PRIOR, ["Algo cambió"])
    assert NOTE_TITLE not in strip_ui_leftovers(noted)
