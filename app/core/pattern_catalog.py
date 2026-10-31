"""Catalogo curado de patrones (data/patterns/*.yaml) y construccion de chunks.

Fuente unica para quien necesite los chunks indexables de un patron:
- scripts/seed_patterns.py los embebe y los guarda en PGVector.
- scripts/eval_pattern_retrieval.py los embebe en memoria para medir el
  retrieval sin base de datos.

Mantener la logica aqui evita que el seed y la evaluacion se desincronicen.

Tipos de chunk:
  summary          descripcion + casos de uso (lenguaje del patron)
  tradeoffs        ventajas y desventajas
  when_not_to_use  cuando NO usarlo (solo baja el patron, ver AVOID_CHUNK_TYPES)
  decision_signals preguntas de decision
  scenarios        escenarios de proyecto redactados como los escribiria un
                   usuario ("equipo de 3 devs, 4 meses...")  <- NUEVO
  fit              atributos de calidad y tamano de equipo ideal  <- NUEVO
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from app.core.text_norm import normalize_text

logger = logging.getLogger(__name__)

PATTERNS_DIR = Path(__file__).resolve().parents[2] / "data" / "patterns"

CHUNK_TYPES = (
    "summary",
    "tradeoffs",
    "when_not_to_use",
    "decision_signals",
    "scenarios",
    "fit",
)


def load_patterns(patterns_dir: Path | None = None) -> list[dict[str, Any]]:
    """Lee todos los YAML del catalogo, ordenados por nombre de archivo."""
    directory = patterns_dir or PATTERNS_DIR
    return [
        yaml.safe_load(path.read_text(encoding="utf-8"))
        for path in sorted(directory.glob("*.yaml"))
    ]


# Familia del patron (campo ``family`` del YAML): agrupa estilos que compiten
# entre si. Sirve para que la tabla de trade-offs compare alternativas REALES
# (un monolito contra un estilo distribuido o serverless) y no tres variantes
# del mismo estilo con similitud parecida (capas, MVC y monolito modular).
VALID_FAMILIES = ("monolitico", "distribuido", "serverless", "datos", "complemento")
# Nivel (campo ``level``): ``despliegue`` = como se despliega el sistema;
# ``codigo`` = como se organiza el codigo por dentro (capas, MVC, hexagonal,
# clean); se combina con un estilo de despliegue, no compite con el.
# ``complemento`` = tactica que se suma a otro estilo (CQRS, Saga, BFF...).
# ``modulo`` = tactica de un modulo concreto (Repository, Service Layer, DTO,
# Unit of Work): no es un estilo de arquitectura y existe para el arbol de
# carpetas, no para la propuesta.
VALID_LEVELS = ("despliegue", "codigo", "complemento", "modulo")

# Niveles que NO compiten como estilo de arquitectura. ``proposal_generator``
# los excluye de las citas y de la tabla de trade-offs: comparar "Repository"
# contra "Microservicios" no le dice nada al usuario, y un proyecto CRUD podria
# hacer que Repository saliera primero en el RAG y desplazara al estilo real.
NON_ARCHITECTURAL_LEVELS = frozenset({"modulo"})

# Tipos de modulo que puede tener un proyecto. Vocabulario compartido entre
# ``applies_to_modules`` en data/patterns/*.yaml y la deteccion de modulos en
# ``app/core/repo_structure.py``. Se valida al cargar: un tipo mal escrito en
# un YAML haria que el patron nunca aplicara y el error pasaria inadvertido.
VALID_MODULE_KINDS = (
    "crud",
    "consulta",
    "reporte",
    "autenticacion",
    "dominio",
    "integracion",
    "procesamiento",
    "mensajeria",
    "api",
    "ui",
    "archivos",
    "notificaciones",
)


@lru_cache(maxsize=1)
def _families_by_name() -> dict[str, dict[str, str]]:
    families: dict[str, dict[str, str]] = {}
    for pattern in load_patterns():
        family = pattern.get("family")
        level = pattern.get("level")
        if family in VALID_FAMILIES and level in VALID_LEVELS:
            families[normalize_text(pattern["pattern_name"])] = {
                "family": family,
                "level": level,
            }
    return families


def pattern_family(pattern_name: str | None) -> dict[str, str] | None:
    """``{"family": ..., "level": ...}`` del patron, o None si no esta en el catalogo.

    Se lee del YAML (no de la base) para no necesitar una migracion: el nombre
    del patron es el mismo en ``architect_patterns`` y en data/patterns/.
    """
    if not pattern_name:
        return None
    return _families_by_name().get(normalize_text(pattern_name))


def build_pattern_chunks(pattern: dict[str, Any]) -> dict[str, str]:
    """Devuelve ``{chunk_type: texto}`` para un patron; omite los vacios."""
    name = pattern["pattern_name"]
    chunks: dict[str, str | None] = {}

    chunks["summary"] = f"{name}: {pattern['description']} {pattern['use_cases']}"

    tradeoffs = pattern.get("tradeoffs") or {}
    if tradeoffs:
        ventajas = "; ".join(tradeoffs.get("ventajas", []))
        desventajas = "; ".join(tradeoffs.get("desventajas", []))
        chunks["tradeoffs"] = f"{name} - ventajas: {ventajas}. Desventajas: {desventajas}."

    if pattern.get("when_not_to_use"):
        chunks["when_not_to_use"] = f"{name} - no usar cuando: {pattern['when_not_to_use']}"

    signals = pattern.get("decision_signals") or []
    if signals:
        preguntas = "; ".join(f"{s['pregunta']} -> {s['señal_patron']}" for s in signals)
        chunks["decision_signals"] = f"{name} - señales de decision: {preguntas}"

    scenarios = pattern.get("example_scenarios") or []
    if scenarios:
        chunks["scenarios"] = f"{name} - proyectos donde encaja: " + " | ".join(
            s.strip() for s in scenarios
        )

    quality = pattern.get("quality_attributes") or []
    team_fit = (pattern.get("team_fit") or "").strip()
    if quality or team_fit:
        parts = []
        if team_fit:
            parts.append(f"equipo y contexto ideal: {team_fit}")
        if quality:
            parts.append("atributos de calidad que favorece: " + ", ".join(quality))
        chunks["fit"] = f"{name} - " + ". ".join(parts) + "."

    return {kind: text for kind, text in chunks.items() if text}


@lru_cache(maxsize=1)
def _sources_by_name() -> dict[str, list]:
    return {
        normalize_text(pattern["pattern_name"]): list(pattern.get("fuentes") or [])
        for pattern in load_patterns()
    }


@lru_cache(maxsize=1)
def _module_index() -> dict[str, dict[str, Any]]:
    """``{nombre normalizado: {"kinds": [...], "contributions": [...]}}``.

    Se lee del YAML y no de la base, igual que ``pattern_family`` y por la
    misma razon: no hace falta una migracion sobre ``architect_patterns`` para
    un campo que solo consume el generador del arbol de carpetas.

    Un ``applies_to_modules`` con un tipo desconocido, o un aporte de
    estructura con un rol desconocido, se registra y se descarta. Antes que
    ubicar una carpeta en un lugar inventado, se prefiere no ubicarla y que el
    generador lo reporte.
    """
    # Import local: ``convention_catalog`` no importa este modulo, pero
    # dejarlo arriba acoplaria el catalogo de patrones al de convenciones para
    # una sola constante.
    from app.core.convention_catalog import ROLES

    index: dict[str, dict[str, Any]] = {}
    for pattern in load_patterns():
        name = pattern.get("pattern_name")
        if not name:
            continue
        kinds: list[str] = []
        for kind in pattern.get("applies_to_modules") or []:
            kind = str(kind).strip()
            if kind not in VALID_MODULE_KINDS:
                logger.error(
                    "Patron '%s': tipo de modulo '%s' desconocido; se ignora",
                    name,
                    kind,
                )
                continue
            kinds.append(kind)

        fuentes = list(pattern.get("fuentes") or [])
        contributions: list[dict[str, Any]] = []
        for raw in pattern.get("structure_contributions") or []:
            if not isinstance(raw, dict):
                logger.error("Patron '%s': aporte de estructura mal formado", name)
                continue
            role = str(raw.get("role") or "").strip()
            if role not in ROLES:
                logger.error(
                    "Patron '%s': rol de estructura '%s' desconocido; se ignora",
                    name,
                    role,
                )
                continue
            source_index = raw.get("source")
            if (
                not isinstance(source_index, int)
                or isinstance(source_index, bool)
                or not 1 <= source_index <= len(fuentes)
            ):
                logger.error(
                    "Patron '%s': el aporte '%s' no apunta a una fuente valida; se ignora",
                    name,
                    role,
                )
                continue
            fuente = fuentes[source_index - 1] or {}
            contributions.append(
                {
                    "role": role,
                    "dir_name": str(raw.get("dir_name") or role),
                    "file_name": str(raw.get("file_name") or role),
                    "class_name": str(raw.get("class_name") or role.title()),
                    "note": " ".join(str(raw.get("note") or "").split()),
                    "source_title": str(fuente.get("titulo") or ""),
                    "source_url": str(fuente.get("url") or ""),
                }
            )

        index[normalize_text(name)] = {
            "pattern_name": name,
            "level": pattern.get("level"),
            "kinds": kinds,
            "contributions": contributions,
        }
    return index


def patterns_for_module_kind(kind: str) -> list[dict[str, Any]]:
    """Patrones cuyo ``applies_to_modules`` incluye ``kind``.

    Es el filtro que pide la historia: la consulta al RAG se restringe a estos
    patrones, asi que el generador nunca propone para un modulo un patron que
    el catalogo no declaro aplicable a ese tipo de modulo.
    """
    if kind not in VALID_MODULE_KINDS:
        return []
    return [
        dict(entry)
        for entry in _module_index().values()
        if kind in entry["kinds"]
    ]


def pattern_module_entry(pattern_name: str | None) -> dict[str, Any] | None:
    """La entrada de modulo del patron, o None si no esta en el catalogo."""
    if not pattern_name:
        return None
    entry = _module_index().get(normalize_text(pattern_name))
    return dict(entry) if entry else None


def is_non_architectural(pattern_name: str | None) -> bool:
    """¿Es un patron de nivel modulo (y por tanto fuera de la propuesta)?"""
    info = pattern_family(pattern_name)
    return bool(info and info["level"] in NON_ARCHITECTURAL_LEVELS)


# Resultado de la auditoria de cobertura, escrito a mano a proposito para que
# la prueba lo compare contra el calculado y avise cuando cambie.
#
# Estos tres tipos de modulo no tienen hoy ningun patron aplicable en la base:
#
#   mensajeria      lo que hay sobre colas y eventos (Event-Driven, Saga,
#                   Event Sourcing) describe como se comunica el SISTEMA, no
#                   como se ordenan las carpetas de un modulo.
#   archivos        no hay en la base ningun patron de almacenamiento de
#                   archivos a nivel de modulo.
#   notificaciones  igual: no hay patron de modulo para esto.
#
# Para un modulo de estos el generador no inventa: lo reporta como "sin patron
# aplicable en la base" con esa razon, que es informacion util y no un hueco
# disimulado. Cerrarlos es trabajo de contenido (escribir los patrones con sus
# fuentes), no de codigo.
KNOWN_UNCOVERED_MODULE_KINDS = ("archivos", "mensajeria", "notificaciones")


def reset_module_index_cache() -> None:
    """Para las pruebas que escriben catalogos temporales."""
    _module_index.cache_clear()
    _families_by_name.cache_clear()
    _sources_by_name.cache_clear()


def module_kinds_without_patterns() -> list[str]:
    """Tipos de modulo que hoy no tienen ningun patron aplicable.

    Es la auditoria de cobertura de la historia, calculada y no escrita a
    mano: si manana se agrega un tipo de modulo y nadie etiqueta un patron
    para el, esto lo delata (y hay una prueba que falla).
    """
    return [kind for kind in VALID_MODULE_KINDS if not patterns_for_module_kind(kind)]


def pattern_sources(pattern_name: str | None) -> list:
    """Fuentes del patrón según el YAML del catálogo ([] si no hay).

    Respaldo para las citas: si la base se sembró antes de que el YAML tuviera
    ``fuentes`` (o no se volvió a sembrar), la cita llegaba sin enlaces y el
    patrón recomendado salía sin referencias en el ADR.
    """
    if not pattern_name:
        return []
    return _sources_by_name().get(normalize_text(pattern_name), [])
