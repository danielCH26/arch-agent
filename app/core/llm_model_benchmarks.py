"""
Loader del YAML de benchmarks MMLU.

Issue: #51 — Wizard de config LLM con tier filter

Lee app/core/llm_model_benchmarks.yaml y expone la lista de modelos
con su score. Cacheado en modulo (el YAML cambia solo via PR).

API:
    load_benchmarks()                  -> list[BenchmarkEntry]
    get_model_score(model_id)          -> float | None
    LLMBenchmarkFileError              -> excepcion si YAML malformado
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)


# Threshold hardcoded — editable aqui si se quiere tunear.
# Tier 1 estricto: >= 85
# Tier 2: 60 <= score < 85
# Blocked: < 60
MMLU_TIER1_THRESHOLD: float = 85.0
MMLU_TIER2_THRESHOLD: float = 60.0


@dataclass(frozen=True)
class BenchmarkEntry:
    """Un modelo con su score MMLU y la fuente."""
    model_id: str
    mmlu_score: float
    source: str


class LLMBenchmarkFileError(Exception):
    """El YAML de benchmarks no existe, esta malformado, o le faltan campos."""


# --- Cache --------------------------------------------------------------------

_lock = threading.Lock()
_cache: Optional[list[BenchmarkEntry]] = None


def _yaml_path() -> Path:
    """Path absoluto al YAML de benchmarks."""
    return Path(__file__).parent / "llm_model_benchmarks.yaml"


def load_benchmarks() -> list[BenchmarkEntry]:
    """
    Carga (y cachea) la lista de benchmarks del YAML.

    Returns:
        Lista de BenchmarkEntry, ordenada como aparece en el YAML.

    Raises:
        LLMBenchmarkFileError: si el archivo no existe, no es YAML valido,
            o no tiene la estructura esperada.
    """
    global _cache
    if _cache is not None:
        return _cache

    with _lock:
        # double-check despues del lock
        if _cache is not None:
            return _cache

        path = _yaml_path()
        if not path.exists():
            raise LLMBenchmarkFileError(
                f"No se encontro el archivo de benchmarks: {path}"
            )

        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as e:
            raise LLMBenchmarkFileError(f"YAML invalido en {path}: {e}")

        if not isinstance(raw, dict) or "models" not in raw:
            raise LLMBenchmarkFileError(
                f"El YAML debe tener una clave 'models' en el top-level. "
                f"Encontrado: {list(raw.keys()) if isinstance(raw, dict) else type(raw).__name__}"
            )

        models_raw = raw["models"]
        if not isinstance(models_raw, list):
            raise LLMBenchmarkFileError(
                f"'models' debe ser una lista, encontrado: {type(models_raw).__name__}"
            )

        entries: list[BenchmarkEntry] = []
        skipped = 0
        for i, item in enumerate(models_raw):
            if not isinstance(item, dict):
                logger.warning("Skipping benchmark entry %d: no es dict", i)
                skipped += 1
                continue

            model_id = item.get("model_id")
            mmlu_score = item.get("mmlu_score")
            source = item.get("source", "(no source)")

            if not isinstance(model_id, str) or not model_id.strip():
                logger.warning("Skipping benchmark entry %d: model_id invalido", i)
                skipped += 1
                continue

            if not isinstance(mmlu_score, (int, float)) or not (0 <= mmlu_score <= 100):
                logger.warning(
                    "Skipping benchmark entry %d (%s): mmlu_score invalido %r",
                    i, model_id, mmlu_score,
                )
                skipped += 1
                continue

            entries.append(BenchmarkEntry(
                model_id=model_id.strip(),
                mmlu_score=float(mmlu_score),
                source=source,
            ))

        if skipped:
            logger.warning(
                "Benchmark YAML: %d entries cargadas, %d saltadas por formato invalido",
                len(entries), skipped,
            )

        _cache = entries
        logger.info("Loaded %d benchmark entries from %s", len(entries), path)
        return entries


def get_model_score(model_id: str) -> Optional[float]:
    """
    Devuelve el MMLU score de un modelo, o None si no esta en el YAML.

    No recarga el YAML cada llamada (usa el cache de load_benchmarks).
    """
    if not model_id:
        return None
    benchmarks = load_benchmarks()
    for entry in benchmarks:
        if entry.model_id == model_id:
            return entry.mmlu_score
    return None


def invalidate_cache() -> None:
    """Invalida el cache (util para tests)."""
    global _cache
    with _lock:
        _cache = None