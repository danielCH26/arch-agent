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

from pathlib import Path
from typing import Any

import yaml

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
