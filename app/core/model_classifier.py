"""
Clasificador de modelos LLM por tier MMLU.

Issue: #51 — Wizard de config LLM con tier filter

Funciones puras (sin I/O, sin DB, sin red) — faciles de testear.

API:
    classify_model(model_id) -> dict   -> {tier, mmlu_score, source}
    filter_by_tier(model_ids) -> dict -> {tier1, unknown_or_tier2, blocked}

Tiers:
    tier1     -> MMLU >= 85 (recomendado, badge verde)
    tier2     -> 60 <= MMLU < 85 (warning, badge amber)
    blocked   -> MMLU < 60 (oculto del dropdown)
    unknown   -> no esta en el YAML (warning, badge amber)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.core.llm_model_benchmarks import (
    MMLU_TIER1_THRESHOLD,
    MMLU_TIER2_THRESHOLD,
    BenchmarkEntry,
    get_model_score,
    load_benchmarks,
)


TIER_RECOMMENDED = "tier1"
TIER_WARNING = "unknown_or_tier2"
TIER_BLOCKED = "blocked"


@dataclass(frozen=True)
class ModelClassification:
    tier: str               # "tier1" | "tier2" | "blocked" | "unknown"
    mmlu_score: Optional[float]
    source: Optional[str]   # URL/cita del YAML, None si es unknown

    def to_dict(self) -> dict:
        return {
            "tier": self.tier,
            "mmlu_score": self.mmlu_score,
            "source": self.source,
        }


def _entry_lookup(model_id: str) -> Optional[BenchmarkEntry]:
    """Busca el entry completo de un modelo en el benchmark file."""
    if not model_id:
        return None
    for entry in load_benchmarks():
        if entry.model_id == model_id:
            return entry
    return None


def classify_model(model_id: str) -> ModelClassification:
    """
    Clasifica un modelo en tier.

    Args:
        model_id: ID del modelo (debe matchear lo que devuelve el provider
                  en su endpoint /models).

    Returns:
        ModelClassification con tier, mmlu_score, source.
    """
    entry = _entry_lookup(model_id)
    if entry is None:
        return ModelClassification(
            tier="unknown",
            mmlu_score=None,
            source=None,
        )

    if entry.mmlu_score >= MMLU_TIER1_THRESHOLD:
        tier = "tier1"
    elif entry.mmlu_score >= MMLU_TIER2_THRESHOLD:
        tier = "tier2"
    else:
        tier = "blocked"

    return ModelClassification(
        tier=tier,
        mmlu_score=entry.mmlu_score,
        source=entry.source,
    )


def is_blocked(model_id: str) -> bool:
    """Shortcut: True si el modelo debe ocultarse (MMLU < 60 o no esta)."""
    return classify_model(model_id).tier == "blocked"


def filter_by_tier(model_ids: list[str]) -> dict[str, list[str]]:
    """
    Particiona una lista de model_ids segun tier.

    Returns:
        {
            "tier1": [...],               # MMLU >= 85, badge "Recomendado"
            "unknown_or_tier2": [...],    # MMLU 60-85 O no esta, badge "Sin score"
            "blocked": [...],             # MMLU < 60, NO aparece en UI
        }

    El orden dentro de cada bucket preserva el orden de model_ids.
    """
    buckets: dict[str, list[str]] = {
        "tier1": [],
        "unknown_or_tier2": [],
        "blocked": [],
    }

    for mid in model_ids:
        classification = classify_model(mid)
        if classification.tier == "tier1":
            buckets["tier1"].append(mid)
        elif classification.tier in ("tier2", "unknown"):
            buckets["unknown_or_tier2"].append(mid)
        else:  # blocked
            buckets["blocked"].append(mid)

    return buckets