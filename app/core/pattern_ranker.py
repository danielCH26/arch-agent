"""Re-ranking de patrones candidatos con el LLM.

La similitud de embeddings recupera candidatos razonables pero no sabe
razonar ("el equipo es de 3 y el plazo de 4 meses, asi que descarta lo
distribuido"). Aqui el LLM ordena SOLO entre los candidatos que ya recupero
el RAG y devuelve una razon por patron.

Garantias:
- Solo puede ordenar patrones de la lista (nombres desconocidos se ignoran).
- No decide por encima de las reglas duras: ``_select_citations`` usa este
  orden unicamente como desempate DESPUES de la descalificacion por escala,
  el rechazo/pedido explicito del usuario y la senal de "no usar".
- Best-effort: si falla, devuelve None y se conserva el orden por similitud.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import unicodedata
from typing import Any

from app.core.query_profile import _message_text, parse_json_object

logger = logging.getLogger(__name__)

RERANK_ENABLED = os.getenv("PROPOSAL_LLM_RERANK", "on").lower() not in {"off", "0", "false"}
RERANK_TIMEOUT_S = float(os.getenv("PROPOSAL_RERANK_TIMEOUT_S", "30"))
# Candidatos que ve el LLM (el RAG ya los ordeno; se queda con los N primeros).
RERANK_POOL_SIZE = int(os.getenv("PROPOSAL_RERANK_POOL", "6"))

_PROMPT = """Eres un arquitecto de software senior. Ordena los patrones candidatos del MEJOR al PEOR ajuste para el proyecto.

Criterios (en este orden): 1) encaja con los requerimientos y atributos de calidad; 2) es proporcional al tamano del equipo, al plazo y al presupuesto (no recomiendes complejidad que el equipo no pueda operar); 3) sus desventajas no chocan con una restriccion del proyecto.

Responde SOLO con JSON valido, sin texto extra ni bloques de codigo:
{{"ranking": ["nombre exacto 1", "nombre exacto 2", ...], "razones": {{"nombre exacto 1": "1 frase ligada a un requisito concreto del proyecto"}}}}
Usa unicamente los nombres de la lista, cada uno una sola vez.

PROYECTO:
{project}

CANDIDATOS:
{candidates}
"""


def _norm(text: str | None) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", (text or "").casefold()) if unicodedata.category(c) != "Mn"
    ).strip()


def _candidate_block(index: int, cite: dict[str, Any]) -> str:
    tradeoffs = cite.get("tradeoffs") or {}
    pros = "; ".join((tradeoffs.get("ventajas") or [])[:2])
    cons = "; ".join((tradeoffs.get("desventajas") or [])[:2])
    return (
        f"{index}. {cite.get('pattern_name')}\n"
        f"   Resumen: {(cite.get('snippet') or '')[:240]}\n"
        f"   Ventajas: {pros}\n   Desventajas: {cons}"
    )


def parse_ranking(raw: str, names: list[str]) -> tuple[list[str], dict[str, str]] | None:
    """Valida la respuesta del LLM contra los nombres reales de los candidatos."""
    data = parse_json_object(raw)
    if not data or not isinstance(data.get("ranking"), list):
        return None
    by_norm = {_norm(n): n for n in names}
    ranking: list[str] = []
    for item in data["ranking"]:
        name = by_norm.get(_norm(str(item)))
        if name and name not in ranking:
            ranking.append(name)
    if not ranking:
        return None
    reasons: dict[str, str] = {}
    raw_reasons = data.get("razones")
    if isinstance(raw_reasons, dict):
        for key, value in raw_reasons.items():
            name = by_norm.get(_norm(str(key)))
            if name and value:
                reasons[name] = " ".join(str(value).split())[:300]
    # Los que el LLM omitio quedan al final, en su orden original.
    ranking += [n for n in names if n not in ranking]
    return ranking, reasons


async def rank_candidates(
    model: Any, project_text: str, candidates: list[dict[str, Any]]
) -> tuple[list[str], dict[str, str]] | None:
    """Pide al LLM ordenar ``candidates``. None si no aplica o si algo falla."""
    if not RERANK_ENABLED or len(candidates) < 2 or not project_text.strip():
        return None
    names = [str(c.get("pattern_name")) for c in candidates if c.get("pattern_name")]
    prompt = _PROMPT.format(
        project=project_text.strip()[:3000],
        candidates="\n".join(_candidate_block(i, c) for i, c in enumerate(candidates, start=1)),
    )
    try:
        message = await asyncio.wait_for(model.ainvoke(prompt), timeout=RERANK_TIMEOUT_S)
        return parse_ranking(_message_text(message), names)
    except Exception as exc:
        logger.warning("Re-ranking con LLM no disponible (%s); se conserva el orden por similitud", exc)
        return None


def ranking_log(ranking: list[str], reasons: dict[str, str]) -> str:
    return json.dumps({"ranking": ranking, "razones": reasons}, ensure_ascii=False)[:600]
