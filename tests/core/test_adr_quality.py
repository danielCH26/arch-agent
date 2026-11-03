"""Verificación previa a la entrega del ADR (app/core/adr_quality.py) y
paridad de la identidad visual entre backend y frontend."""

from __future__ import annotations

import re
from pathlib import Path

from app.core.adr_quality import project_terms, section_issues, split_sections
from app.core.adr_theme import ADR_FONTS, ADR_PALETTE, mermaid_theme_config, themed_mermaid

TERMS = project_terms(["Agenda de citas para la clínica", "PostgreSQL y React"])


def test_las_palabras_genericas_no_son_del_proyecto():
    assert {"agenda", "citas", "clinica", "postgresql", "react"} <= TERMS
    assert not {"sistema", "usuarios", "para"} & TERMS


def test_seccion_vacia_o_con_solo_un_marcador():
    assert [str(i) for i in section_issues("Restricciones", "", TERMS)] == ["«Restricciones»: está vacía"]
    assert [str(i) for i in section_issues("Restricciones", "_No especificado._", TERMS)] == [
        "«Restricciones»: solo tiene un marcador, sin contenido"
    ]


def test_seccion_generica_corta_y_con_relleno():
    issues = [i.problem for i in section_issues("7.3 Consecuencias", "Hay que seguir buenas prácticas.", TERMS)]
    assert any(p.startswith("es muy corta") for p in issues)
    assert any(p.startswith("es genérica") for p in issues)
    assert any("seguir buenas practicas" in p for p in issues)


def test_seccion_especifica_pasa():
    body = "| Capa | Tecnología |\n|---|---|\n| Datos | PostgreSQL para la agenda de citas de la clínica |"
    assert section_issues("7.2 Stack", body, TERMS) == []


def test_split_sections_no_toma_comentarios_de_un_bloque_de_codigo():
    md = "## 1. A\ntexto\n```\n## no es titulo\n```\n### sub\nmas\n## 2. B\notro"
    assert [t for t, _ in split_sections(md, 2)] == ["1. A", "2. B"]
    assert "## no es titulo" in split_sections(md, 2)[0][1]


def test_themed_mermaid_agrega_el_tema_y_respeta_uno_propio():
    themed = themed_mermaid("flowchart TD\n  A --> B")
    assert themed.startswith("%%{init: {") and themed.endswith("flowchart TD\n  A --> B")
    assert ADR_PALETTE["primary"] in themed
    own = "%%{init: {'theme': 'dark'}}%%\nflowchart TD\n  A --> B"
    assert themed_mermaid(own) == own
    assert mermaid_theme_config()["theme"] == "base"


def test_themed_mermaid_va_despues_del_frontmatter():
    """Mermaid solo reconoce el frontmatter en la primera línea."""
    code = "---\ntitle: Agenda\n---\nflowchart TD\n  A --> B"
    themed = themed_mermaid(code)
    assert themed.startswith("---\ntitle: Agenda\n---\n%%{init: {")
    assert themed.endswith("%%\nflowchart TD\n  A --> B")
    assert themed.count("%%{init") == 1


def test_themed_mermaid_respeta_el_tema_del_frontmatter():
    code = "---\nconfig:\n  theme: forest\n---\nflowchart TD\n  A --> B"
    assert themed_mermaid(code) == code


def test_themed_mermaid_no_duplica_una_directiva_con_espacio_o_tras_un_comentario():
    for own in (
        "%%{ init: {'theme': 'dark'}}%%\nflowchart TD\n  A --> B",
        "%% Diagrama de la agenda\n%%{init: {'theme': 'dark'}}%%\nflowchart TD",
        "%%{initialize: {'theme': 'dark'}}%%\nflowchart TD",
        "---\ntitle: Agenda\n---\n%%{ init: {'theme': 'dark'}}%%\nflowchart TD",
    ):
        assert themed_mermaid(own) == own
    # Un comentario no es una directiva: el tema se agrega.
    assert themed_mermaid("%% solo un comentario\nflowchart TD").startswith("%%{init: {")


def _ts_block(name: str) -> str:
    ts = (Path(__file__).resolve().parents[2] / "frontend/src/components/adrTheme.ts").read_text(encoding="utf-8")
    return ts.split(f"export const {name}", 1)[1].split("} as const", 1)[0]


def test_la_paleta_del_pdf_es_la_misma_que_la_de_los_diagramas():
    """adrTheme.ts (PDF) y adr_theme.py (Mermaid) no se pueden separar."""
    frontend = dict(re.findall(r"^\s*(\w+):\s*'(#[0-9A-Fa-f]{6})'", _ts_block("ADR_PALETTE"), re.M))
    assert frontend == ADR_PALETTE


def test_las_tipografias_del_pdf_son_las_mismas_que_las_de_los_diagramas():
    frontend = dict(re.findall(r'^\s*(\w+):\s*"([^"]+)"', _ts_block("ADR_FONTS"), re.M))
    assert frontend == ADR_FONTS


def test_las_siglas_del_titulo_son_las_mismas_en_el_frontend():
    """"prueba adr" se muestra "Prueba ADR" en el ADR y en la app."""
    from app.core.adr_generator import DISPLAY_ACRONYMS

    ts = (Path(__file__).resolve().parents[2] / "frontend/src/lib/format.ts").read_text(encoding="utf-8")
    block = ts.split("const DISPLAY_ACRONYMS = new Set([", 1)[1].split("])", 1)[0]
    assert set(re.findall(r"'(\w+)'", block)) == DISPLAY_ACRONYMS
