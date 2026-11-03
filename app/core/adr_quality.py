"""Verificación previa a la entrega del ADR: cada sección debe aportar.

Revisión determinista (sin LLM) del markdown ya armado. Una sección no pasa si:

* está vacía o solo tiene un marcador (``_No especificado._``);
* es muy corta para lo que tiene que decir;
* es genérica: no nombra nada propio del proyecto (sus funcionalidades,
  tecnologías, componentes del diagrama, usuarios, restricciones...). Una
  lista de riesgos que serviría para cualquier sistema no le sirve al equipo;
* tiene frases de relleno ("seguir buenas prácticas", "según sea necesario").

El vocabulario del proyecto sale de lo que el usuario dijo y de lo que se
aprobó (``project_terms``). Las palabras que aparecen en cualquier ADR
("sistema", "usuarios", "datos") no cuentan como específicas.

Este módulo no conoce ``AdrContext``: ``adr_generator`` le pasa los textos.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from app.core.text_norm import normalize_text

# Palabras que salen en el ADR de cualquier proyecto: no prueban que una
# sección hable de ESTE proyecto.
GENERIC_WORDS = frozenset(
    """
    sistema sistemas usuario usuarios dato datos proyecto proyectos arquitectura
    aplicacion aplicaciones servicio servicios componente componentes equipo
    plataforma base bases gestion informacion funcionalidad funcionalidades
    requisito requisitos requerimiento requerimientos calidad seguridad
    disponibilidad rendimiento escalabilidad mantenibilidad costo costos riesgo
    riesgos impacto mitigacion fase fases plan sprint tarea tareas objetivo
    entregable entregables criterio terminado capa capas tecnologia tecnologias
    stack modulo modulos repositorio carpeta carpetas codigo pruebas prueba
    tests test documentacion despliegue produccion desarrollo ambiente entorno
    para como esta este esto estos estas entre sobre desde hasta donde cuando
    porque tiene tienen debe deben puede pueden hacer usar uso cada todo todos
    toda todas otro otros otra otras mismo misma nuevo nueva primer primera
    segundo segunda alto alta medio media bajo baja mayor menor mejor solo
    solucion problema problemas decision decisiones propuesta opcion opciones
    principal general inicial final semana semanas meses tiempo nivel parte
    the and with from that this
    """.split()
)

# Frases que no dicen nada concreto. Normalizadas (sin acentos, minúsculas).
FILLER_PHRASES = (
    "lorem ipsum",
    "texto de ejemplo",
    "seguir las buenas practicas",
    "seguir buenas practicas",
    "aplicar buenas practicas",
    "aplicar las buenas practicas",
    "segun sea necesario",
    "segun corresponda",
    "dependera del contexto",
    "depende del contexto",
    "tbd",
    "todo:",
)

# Mínimos para no ser relleno: caracteres de texto real y términos del
# proyecto distintos.
MIN_SECTION_CHARS = 60
MIN_PROJECT_TERMS = 2

_PLACEHOLDER_LINE_RE = re.compile(r"^\s*[-*]?\s*_[^_]+_\s*$")
_WORD_RE = re.compile(r"[a-z0-9][a-z0-9+#.-]{2,}")


@dataclass(frozen=True)
class SectionIssue:
    section: str
    problem: str

    def __str__(self) -> str:
        return f"«{self.section}»: {self.problem}"


def _words(text: str) -> set[str]:
    return {w.strip(".-") for w in _WORD_RE.findall(normalize_text(text))}


def project_terms(texts: Iterable[str]) -> set[str]:
    """Vocabulario propio del proyecto a partir de lo dicho y lo aprobado."""
    terms: set[str] = set()
    for text in texts:
        terms |= {w for w in _words(text or "") if len(w) >= 3 and w not in GENERIC_WORDS}
    return terms


def plain_text(markdown: str) -> str:
    """Texto que lee una persona: sin marcas, filetes de tabla ni marcadores."""
    lines = []
    for line in (markdown or "").splitlines():
        if _PLACEHOLDER_LINE_RE.match(line) or re.match(r"^\s*\|?\s*:?-{3,}", line):
            continue
        if line.strip().startswith(("```", ">")) or re.match(r"^\s*#{1,6}\s", line):
            continue
        lines.append(line)
    text = re.sub(r"[*_`|#]", " ", "\n".join(lines))
    return re.sub(r"\s+", " ", text).strip()


def section_issues(
    title: str,
    body: str,
    terms: set[str],
    *,
    min_chars: int = MIN_SECTION_CHARS,
    min_terms: int = MIN_PROJECT_TERMS,
    check_specific: bool = True,
) -> list[SectionIssue]:
    """Problemas de una sección. Una vacía no se revisa por nada más."""
    text = plain_text(body)
    if not text:
        only_marker = any(_PLACEHOLDER_LINE_RE.match(line) for line in (body or "").splitlines())
        return [SectionIssue(title, "solo tiene un marcador, sin contenido" if only_marker else "está vacía")]
    issues = []
    if len(text) < min_chars:
        issues.append(SectionIssue(title, f"es muy corta ({len(text)} caracteres)"))
    if check_specific and terms:
        found = _words(text) & terms
        if len(found) < min_terms:
            issues.append(
                SectionIssue(title, "es genérica: no nombra nada propio del proyecto (funcionalidades, "
                "tecnologías, componentes o restricciones)")
            )
    normalized = normalize_text(text)
    fillers = [p for p in FILLER_PHRASES if re.search(rf"(?<![a-z]){re.escape(p)}(?![a-z])", normalized)]
    if fillers:
        issues.append(SectionIssue(title, "tiene texto de relleno: " + ", ".join(f"«{p}»" for p in fillers)))
    return issues


def split_sections(markdown: str, level: int) -> list[tuple[str, str]]:
    """``[(titulo, cuerpo)]`` de los encabezados de exactamente ``level`` ``#``.

    El cuerpo llega hasta el siguiente encabezado de ese nivel o uno mayor; los
    bloques de código no se miran (un ``#`` dentro de un árbol de carpetas no
    es un título).
    """
    sections: list[tuple[str, list[str]]] = []
    in_fence = False
    for line in (markdown or "").splitlines():
        if line.strip().startswith("```"):
            in_fence = not in_fence
        heading = None if in_fence else re.match(r"^(#{1,6})\s+(.*)$", line)
        if heading and len(heading.group(1)) <= level:
            if len(heading.group(1)) == level:
                sections.append((heading.group(2).strip(), []))
            else:
                sections.append(("", []))  # un título mayor cierra la sección
            continue
        if sections:
            sections[-1][1].append(line)
    return [(title, "\n".join(body).strip()) for title, body in sections if title]
