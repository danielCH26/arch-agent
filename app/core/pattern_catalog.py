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

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from app.core.text_norm import normalize_text

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
VALID_LEVELS = ("despliegue", "codigo", "complemento")


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


def pattern_sources(pattern_name: str | None) -> list:
    """Fuentes del patrón según el YAML del catálogo ([] si no hay).

    Respaldo para las citas: si la base se sembró antes de que el YAML tuviera
    ``fuentes`` (o no se volvió a sembrar), la cita llegaba sin enlaces y el
    patrón recomendado salía sin referencias en el ADR.
    """
    if not pattern_name:
        return []
    return _sources_by_name().get(normalize_text(pattern_name), [])
