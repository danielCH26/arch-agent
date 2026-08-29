"""
Lógica pura de selección y filtrado de modelos LLM.

Issue: #7 - HU12 Configuración de LLM

Extraído de app.llm.config_form (que dependía de Chainlit). Estas funciones
son independientes de la UI — las consume la SPA React vía el endpoint
GET /api/llm/models?filter=... y los tests unitarios.

Funciones exportadas:
- filter_models(models, filter_text)        -> lista filtrada
- split_visible_and_excess(filtered, max)   -> (visible, count_oculto)
- match_model_exact(models, user_input)     -> nombre real o None
- is_filter_refinement(user_input, models)  -> bool
- MAX_BUTTONS                                límite de botones en UI legacy
"""

from typing import Optional

# Máximo de botones visibles para no saturar UI (legacy — la SPA usa paginación).
MAX_BUTTONS = 20


def filter_models(models: list[str], filter_text: str) -> list[str]:
    """
    Filtra modelos por substring case-insensitive.

    Args:
        models: lista completa de modelos
        filter_text: texto a buscar (vacío = todos)

    Returns:
        Lista filtrada (preserva orden original)
    """
    if not filter_text or not filter_text.strip():
        return list(models)
    needle = filter_text.strip().lower()
    return [m for m in models if needle in m.lower()]


def split_visible_and_excess(
    filtered: list[str], max_visible: int = MAX_BUTTONS
) -> tuple[list[str], int]:
    """
    Divide los modelos filtrados en visibles y el resto.

    Returns:
        (visible, excess_count)
    """
    if len(filtered) <= max_visible:
        return list(filtered), 0
    return list(filtered[:max_visible]), len(filtered) - max_visible


def match_model_exact(models: list[str], user_input: str) -> Optional[str]:
    """
    Busca match exacto (case-insensitive) de un modelo.

    Returns:
        El nombre real del modelo si hay match, None si no.
    """
    if not user_input:
        return None
    user_input = user_input.strip()
    # Match exacto (case-sensitive)
    if user_input in models:
        return user_input
    # Match case-insensitive
    for m in models:
        if m.lower() == user_input.lower():
            return m
    return None


def is_filter_refinement(user_input: str, models: list[str]) -> bool:
    """
    Determina si el input del usuario es un refinamiento de filtro
    (no es un nombre de modelo exacto pero matchea algunos).
    """
    if not user_input:
        return False
    user_input = user_input.strip().lower()
    # Si es match exacto, NO es refinamiento
    if user_input in [m.lower() for m in models]:
        return False
    # Si matchea algún modelo, ES refinamiento
    return any(user_input in m.lower() for m in models)
