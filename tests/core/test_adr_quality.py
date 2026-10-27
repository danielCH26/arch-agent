"""Verificación previa a la entrega del ADR (app/core/adr_quality.py) y
paridad de la identidad visual entre backend y frontend."""

from __future__ import annotations

import re
from pathlib import Path

from app.core.adr_quality import project_terms, section_issues, split_sections
from app.core.adr_theme import ADR_PALETTE, mermaid_theme_config, themed_mermaid

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


def test_la_paleta_del_pdf_es_la_misma_que_la_de_los_diagramas():
    """adrTheme.ts (PDF) y adr_theme.py (Mermaid) no se pueden separar."""
    ts = (Path(__file__).resolve().parents[2] / "frontend/src/components/adrTheme.ts").read_text(encoding="utf-8")
    block = ts.split("export const ADR_PALETTE", 1)[1].split("} as const", 1)[0]
    frontend = dict(re.findall(r"^\s*(\w+):\s*'(#[0-9A-Fa-f]{6})'", block, re.M))
    assert frontend == ADR_PALETTE
