"""Perfil estructurado del proyecto para consultar la base de patrones.

Problema: la consulta al RAG era "nombre + descripcion + 1500 caracteres de
requerimientos". Ese texto no se parece al de un patron (que habla de
"desacoplamiento", "puertos y adaptadores"...), asi que la similitud coseno
quedaba en una banda estrecha y discriminaba poco.

Solucion: una llamada barata al LLM resume el proyecto en un perfil
(dominio, tipo de sistema, equipo, plazo, escala, atributos de calidad...) y
con el se arma una consulta redactada como los chunks ``scenarios`` y ``fit``
del catalogo (ver app/core/pattern_catalog.py).

Todo es best-effort: si el modelo no responde, tarda o devuelve algo que no es
JSON, ``extract_project_profile`` devuelve ``None`` y el caller usa la consulta
anterior. Nunca bloquea la generacion.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Any

logger = logging.getLogger(__name__)

PROFILE_ENABLED = os.getenv("PROPOSAL_QUERY_PROFILE", "on").lower() not in {"off", "0", "false"}
PROFILE_TIMEOUT_S = float(os.getenv("PROPOSAL_PROFILE_TIMEOUT_S", "25"))
PROFILE_INPUT_MAX_CHARS = 6000

PROJECT_KINDS = {"mvp_prototipo", "academico", "producto_en_produccion", "empresarial", "desconocido"}

_PROFILE_PROMPT = """Eres un analista de requerimientos. Resume el proyecto en un JSON.

Responde SOLO con un objeto JSON valido, sin texto antes ni despues y sin bloques de codigo.
Reglas:
- Usa null (o [] / "") cuando el texto NO lo diga de forma explicita. No inventes cifras.
- NO menciones nombres de patrones o estilos de arquitectura (microservicios, CQRS, hexagonal...) a menos que el texto los nombre.
- "resumen": 1 o 2 frases en espanol que describan el problema que resuelve el sistema.

Esquema:
{{
  "resumen": "string",
  "dominio": "string (p. ej. salud, e-commerce, educacion, finanzas, logistica)",
  "tipo_sistema": "string (p. ej. aplicacion web, app movil, API, pipeline de datos, plataforma de analitica, sistema de modelos de ML)",
  "tipo_proyecto": "mvp_prototipo | academico | producto_en_produccion | empresarial | desconocido",
  "equipo_personas": "entero o null",
  "plazo_meses": "entero o null",
  "presupuesto_usd": "entero o null",
  "escala": "string corto (p. ej. decenas de usuarios, miles de usuarios concurrentes, millones de eventos al dia)",
  "atributos_calidad": ["lista corta: escalabilidad, disponibilidad, seguridad, rendimiento, modificabilidad, auditabilidad, tiempo real..."],
  "integraciones": ["sistemas externos o fuentes de datos mencionados"],
  "restricciones": ["restricciones tecnicas o de negocio explicitas"]
}}

PROYECTO:
{text}
"""


def _coerce_int(value: Any, low: int, high: int) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = int(float(str(value).replace(",", "").strip()))
    except (TypeError, ValueError):
        return None
    return number if low <= number <= high else None


def _coerce_str(value: Any, limit: int = 300) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _coerce_list(value: Any, max_items: int = 8) -> list[str]:
    if not isinstance(value, list):
        return []
    items = [_coerce_str(v, 120) for v in value]
    return [i for i in items if i][:max_items]


def _message_text(message: Any) -> str:
    """Texto de la respuesta de un chat model (str o lista de bloques)."""
    content = getattr(message, "content", message)
    if isinstance(content, list):
        return "".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in content
        )
    return str(content or "")


def parse_json_object(raw: str) -> dict[str, Any] | None:
    """Extrae el primer objeto JSON de ``raw`` (tolera ```json y texto extra)."""
    if not raw:
        return None
    text = re.sub(r"```(?:json)?", "", raw).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def normalize_profile(data: dict[str, Any] | None) -> dict[str, Any] | None:
    """Valida tipos y rangos; devuelve None si no queda nada util."""
    if not data:
        return None
    kind = _coerce_str(data.get("tipo_proyecto"), 40).lower()
    profile = {
        "resumen": _coerce_str(data.get("resumen"), 400),
        "dominio": _coerce_str(data.get("dominio"), 80),
        "tipo_sistema": _coerce_str(data.get("tipo_sistema"), 80),
        "tipo_proyecto": kind if kind in PROJECT_KINDS else "desconocido",
        "equipo_personas": _coerce_int(data.get("equipo_personas"), 1, 500),
        "plazo_meses": _coerce_int(data.get("plazo_meses"), 1, 120),
        "presupuesto_usd": _coerce_int(data.get("presupuesto_usd"), 1, 100_000_000),
        "escala": _coerce_str(data.get("escala"), 120),
        "atributos_calidad": _coerce_list(data.get("atributos_calidad")),
        "integraciones": _coerce_list(data.get("integraciones")),
        "restricciones": _coerce_list(data.get("restricciones")),
    }
    useful = profile["resumen"] or profile["tipo_sistema"] or profile["dominio"]
    return profile if useful else None


async def extract_project_profile(model: Any, text: str) -> dict[str, Any] | None:
    """Pide al LLM el perfil del proyecto. Best-effort: None si algo falla."""
    if not PROFILE_ENABLED or not text or not text.strip():
        return None
    prompt = _PROFILE_PROMPT.format(text=text.strip()[:PROFILE_INPUT_MAX_CHARS])
    try:
        message = await asyncio.wait_for(model.ainvoke(prompt), timeout=PROFILE_TIMEOUT_S)
        profile = normalize_profile(parse_json_object(_message_text(message)))
    except Exception as exc:  # modelo sin ainvoke, timeout, red, JSON roto...
        logger.warning("Perfil del proyecto no disponible (%s); se usa la consulta clasica", exc)
        return None
    if profile is None:
        logger.warning("Perfil del proyecto vacio o invalido; se usa la consulta clasica")
    return profile


def profile_to_query(profile: dict[str, Any] | None, fallback: str) -> str:
    """Consulta para el RAG redactada como un escenario de proyecto.

    Imita el estilo de los chunks ``scenarios`` / ``fit`` ("equipo de 3
    desarrolladores, 4 meses, ...") para que la similitud los favorezca. Si no
    hay perfil devuelve ``fallback`` (la consulta anterior).
    """
    if not profile:
        return fallback
    parts: list[str] = []
    head = " ".join(
        p for p in (profile["tipo_sistema"], f"para {profile['dominio']}" if profile["dominio"] else "") if p
    )
    if head:
        parts.append(f"Proyecto: {head}.")
    if profile["resumen"]:
        parts.append(profile["resumen"])
    context = []
    if profile["equipo_personas"]:
        context.append(f"equipo de {profile['equipo_personas']} personas")
    if profile["plazo_meses"]:
        context.append(f"plazo de {profile['plazo_meses']} meses")
    if profile["tipo_proyecto"] in {"mvp_prototipo", "academico"}:
        context.append("MVP" if profile["tipo_proyecto"] == "mvp_prototipo" else "proyecto académico")
    if profile["escala"]:
        context.append(f"escala: {profile['escala']}")
    if context:
        parts.append(", ".join(context).capitalize() + ".")
    if profile["atributos_calidad"]:
        parts.append("Atributos de calidad: " + ", ".join(profile["atributos_calidad"]) + ".")
    if profile["integraciones"]:
        parts.append("Integraciones: " + ", ".join(profile["integraciones"]) + ".")
    if profile["restricciones"]:
        parts.append("Restricciones: " + "; ".join(profile["restricciones"]) + ".")
    return " ".join(parts) or fallback


def profile_to_constraints_text(profile: dict[str, Any] | None) -> str:
    """Frases con el formato que reconocen las heuristicas de escala.

    ``_small_scale_signal`` / ``_tight_mvp_constraint`` (proposal_generator) usan
    regex sobre el texto del usuario ("equipo de 3 personas", "4 meses",
    "mvp"). Cuando el requerimiento lo dice de otra forma ("somos tres
    estudiantes", "tenemos un cuatrimestre") esas regex no disparan; el perfil
    las alimenta con la misma informacion normalizada.

    Solo emite cifras y marcas fijas, NUNCA texto libre del LLM: asi el modelo
    no puede colar el nombre de un patron y activar ``_explicitly_requested``.
    """
    if not profile:
        return ""
    sentences = []
    if profile["equipo_personas"]:
        sentences.append(f"equipo de {profile['equipo_personas']} personas")
    if profile["plazo_meses"]:
        sentences.append(f"plazo de {profile['plazo_meses']} meses")
    if profile["presupuesto_usd"]:
        sentences.append(f"presupuesto de ${profile['presupuesto_usd']} usd")
    if profile["tipo_proyecto"] == "mvp_prototipo":
        sentences.append("mvp")
    elif profile["tipo_proyecto"] == "academico":
        sentences.append("proyecto academico")
    return "; ".join(sentences)
