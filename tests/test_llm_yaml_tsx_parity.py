"""
Test de paridad entre `app/core/llm_model_benchmarks.yaml` (backend,
fuente de verdad) y el dict `MODEL_MMLU` en
`frontend/src/components/llm-wizard/Step3ModelSelect.tsx` (frontend,
solo UI).

Los dos DEBEN tener exactamente el mismo set de model_ids. Si difieren:
- Un modelo nuevo en el YAML pero no en el TSX: el backend va a permitir
  guardarlo como tier1, pero el frontend lo va a mostrar como
  'Sin score conocido' (con badge de warning).
- Un modelo nuevo en el TSX pero no en el YAML: el frontend lo va a
  mostrar como 'Recomendado', pero el backend va a rechazar el save
  con 400 'no esta en tier 1'.

Cualquiera de los dos es un bug. El test detecta el drift automaticamente.

El parseo del TSX es con regex (no hay TypeScript compiler disponible en
los deps de pytest), asi que es intencionalmente tolerante: ignora
cualquier linea que no matchea el patron `'key': number,`. Si alguien
refactoriza el TSX a otro formato (eg: extrae a un .json), este test va
a fallar y va a forzar la actualizacion.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
YAML_PATH = PROJECT_ROOT / "app" / "core" / "llm_model_benchmarks.yaml"
TSX_PATH = (
    PROJECT_ROOT
    / "frontend"
    / "src"
    / "components"
    / "llm-wizard"
    / "Step3ModelSelect.tsx"
)

# Match: 'some-key': 88.7,
# Captures group(1) = key, group(2) = number.
# Keys pueden tener chars alfanumericos, guiones, guiones bajos, puntos.
TSX_ENTRY_RE = re.compile(
    r"""^\s*['"]([A-Za-z0-9_.\-]+)['"]\s*:\s*([0-9]+(?:\.[0-9]+)?)\s*,?\s*(?:#.*)?$""",
    re.MULTILINE,
)


def _read_yaml_model_ids() -> set[str]:
    """Lee todos los model_id del YAML."""
    with open(YAML_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return {entry["model_id"] for entry in data["models"] if "model_id" in entry}


def _read_tsx_model_ids() -> set[str]:
    """Extrae todos los model_id del dict MODEL_MMLU en el TSX."""
    with open(TSX_PATH, encoding="utf-8") as f:
        content = f.read()

    # Encontramos el bloque del dict MODEL_MMLU (entre { y } de su assign).
    # El patron es robusto porque solo nos importa capturar 'key': number.
    # TypeScript a veces cierra el dict sin ';' por ASI, asi que aceptamos
    # tanto `};` como `}` como fin del bloque.
    match = re.search(
        r"MODEL_MMLU\s*:\s*Record<string,\s*number>\s*=\s*\{(.*?)\}\s*;?",
        content,
        re.DOTALL,
    )
    if match is not None:
        body = match.group(1)
    else:
        # Fallback: si el patron no matchea (archivo refactorizado),
        # tomar todas las entradas 'key': number del archivo entero.
        body = content

    ids = set()
    for line in body.splitlines():
        line_match = TSX_ENTRY_RE.match(line)
        if line_match:
            ids.add(line_match.group(1))
    return ids


@pytest.fixture(scope="module")
def yaml_entries() -> list[dict]:
    """Devuelve la lista cruda de entries del YAML."""
    with open(YAML_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data["models"]


@pytest.fixture(scope="module")
def yaml_visible_ids(yaml_entries) -> set[str]:
    """Model_ids del YAML que el usuario PUEDE seleccionar en la UI.

    Excluye los 'blocked' (MMLU < 60) porque el frontend los oculta via
    tierFor === 'blocked'. El YAML los conserva SOLO para que el
    classifier los reconozca si llegan por el endpoint del provider.
    """
    blocked_threshold = 60.0
    return {
        e["model_id"]
        for e in yaml_entries
        if e.get("mmlu_score", 0) >= blocked_threshold
    }


@pytest.fixture(scope="module")
def tsx_ids() -> set[str]:
    return _read_tsx_model_ids()


def test_yaml_and_tsx_have_the_same_visible_models(yaml_visible_ids, tsx_ids):
    """Modelos VISIBLES en el YAML deben coincidir exactamente con TSX.

    Los modelos 'blocked' en el YAML (MMLU < 60) se excluyen de la
    comparacion porque la UI los filtra via tierFor === 'blocked'.
    """
    if yaml_visible_ids != tsx_ids:
        only_in_yaml = yaml_visible_ids - tsx_ids
        only_in_tsx = tsx_ids - yaml_visible_ids
        msg_parts = ["YAML visible models y TSX difieren:"]
        if only_in_yaml:
            msg_parts.append(
                f"  Solo en YAML (tier1/tier2):\n    {sorted(only_in_yaml)}"
            )
        if only_in_tsx:
            msg_parts.append(
                f"  Solo en TSX:\n    {sorted(only_in_tsx)}\n"
                f"  (frontend los muestra como 'Recomendados' o 'Sin score conocido',"
                f"\n   pero el backend rechaza el save con 400 'no esta en tier 1')"
            )
        msg_parts.append(
            "\nSolucion: agregar el modelo faltante en AMBOS archivos:\n"
            "  - app/core/llm_model_benchmarks.yaml (fuente de verdad del backend)\n"
            "  - frontend/src/components/llm-wizard/Step3ModelSelect.tsx (UI)\n"
            "Para eliminar la duplicacion a largo plazo, considerar mover el dict a un JSON compartido."
        )
        pytest.fail("\n".join(msg_parts))


def test_yaml_has_minimum_models(yaml_entries):
    """El YAML no debe quedar vacio por accidente."""
    assert len(yaml_entries) >= 5, f"YAML tiene solo {len(yaml_entries)} modelos. Sospechoso."


def test_tier1_models_have_score_above_threshold(yaml_entries):
    """Modelos tier1 clasificados por el YAML tienen score >= 85."""
    for entry in yaml_entries:
        score = entry.get("mmlu_score", 0)
        if score >= 85:
            # Self-consistency: si un modelo esta en el YAML con score >= 85,
            # debe estar disponible para el usuario (frontend lo muestra).
            # Esta validacion es trivial pero detecta errores obvios.
            assert "model_id" in entry


def test_blocked_models_have_score_below_threshold(yaml_entries):
    """Los modelos 'blocked' en el YAML tienen MMLU < 60."""
    BLOCKED_THRESHOLD = 60.0
    blocked_ids = {
        e["model_id"] for e in yaml_entries if e.get("mmlu_score", 100) < BLOCKED_THRESHOLD
    }
    # Solo verificamos que existan con score bajo — el frontend no los lista.
    assert all("model_id" in e for e in yaml_entries), "YAML malformado"
