"""
Lógica del agente de elicitación: preguntas progresivas, punto de decisión
(¿contexto suficiente?) y resumen del contexto capturado.

Issue: [F05] Elicitación guiada + aprobación

Recibe el modelo LangChain ya construido (build_langchain_model) en vez de
construirlo internamente, para poder testear next_step()/generate_summary()
con un modelo fake, sin necesitar credenciales ni red -- mismo criterio de
separación que ya usa model_classifier.py en este mismo paquete.
"""

from __future__ import annotations

import json
import logging
import os
import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from app.core.domain_concerns import concern_by_question, relevant_concerns, uncovered_concerns
from app.core.llm_loader import invoke_with_temperature_fallback

_LOGGER = logging.getLogger(__name__)

# Reglas duras que NO dependen del LLM -- evitan que el agente "se rinda"
# demasiado pronto o se alargue indefinidamente, sin importar lo que
# decida el modelo.
MIN_QUESTIONS = 5
MAX_QUESTIONS = 10
# Proyectos complejos (varias fuentes de datos o sistemas a integrar, varias
# sedes, tiempo real, modelos predictivos, muchas preocupaciones del dominio):
# con 10 preguntas el agente cerraba sin preguntar por fuentes adicionales,
# frescura de los datos, menores de edad o retención (prueba del observatorio
# de analítica). Ver ``max_questions``.
MAX_QUESTIONS_COMPLEX = int(os.getenv("ELICITATION_MAX_QUESTIONS_COMPLEX", "14") or 14)

# Estos tres datos no son una restricción genérica más: determinan si una
# propuesta es viable. Se buscan en las RESPUESTAS del usuario, en la
# descripción y en los documentos (nunca en el texto de las preguntas, que casi
# siempre nombran el tema aunque no se haya respondido) para no volver a
# preguntar lo ya conocido.
#
# Cada término es un fragmento de regex que se compara sobre texto sin acentos
# y en minúsculas, con límites de palabra (ver ``_factor_regex``): "mes" ya no
# coincide con "mesa" ni "cop" con "copia". Se evitan términos genéricos que
# aparecen en otros contextos ("tiempo de respuesta", "500 personas usarán el
# sistema", "100 USD al mes") y palabras del dominio del proyecto ("reducir
# costos de envío", "equipos de gimnasio"): el plazo exige una cantidad ("3
# meses", "12 semanas"), el presupuesto la palabra "presupuesto" o un monto
# ("5000usd", "$20.000", "10 mil pesos") y el equipo la palabra "equipo" en
# singular, un conteo ("somos 3", "3 desarrolladores") o un rol con seniority.
_NUMBER = r"(?:\d+|un|una|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|doce)"
_MONEY_AMOUNT = r"\d[\d.,]*(?:\s*(?:k|mil|millones?))?"
_DEV_ROLE = r"(?:desarrollador(?:es)?|programador(?:es)?|developers?|devs?|ingenier[oa]s?\s+de\s+software)"
# Roles que también cuentan como integrantes del equipo cuando vienen con un
# número ("2 ingenieros de datos, 1 analista de Power BI").
_TEAM_ROLE = (
    r"(?:ingenier[oa]s?|analistas?|disenador(?:a|es|as)?|cientific[oa]s?\s+de\s+datos|"
    r"testers?|qa|pm|lider(?:es)?\s+tecnic[oa]s?|arquitect[oa]s?|personas\s+en\s+el\s+equipo)"
)
_VIABILITY_FACTORS = (
    (
        "presupuesto",
        (
            r"presupuestos?",
            # monto + moneda, sin exigir espacio: "5000usd", "20000cop", "10 mil pesos"
            _MONEY_AMOUNT + r"\s*(?:de\s+)?(?:usd|cop|dolar(?:es)?|pesos?)",
            # moneda + monto: "USD 5000", "$20.000"
            r"(?:usd|cop|us\$)\s*" + _MONEY_AMOUNT,
            r"\$\s*" + _MONEY_AMOUNT,
            r"inversion\s+(?:inicial|maxima|total|disponible|limitada)",
        ),
        "¿Con qué presupuesto cuentan para construir y operar el sistema? Si aún no está definido, indícame el rango o la restricción de gasto.",
    ),
    (
        "equipo",
        (
            # Antes bastaba la palabra "equipo": "Bienestar y el equipo de
            # planeación" (una lista de USUARIOS) daba el equipo por respondido
            # y nunca se preguntaba el tamaño. Ahora tiene que hablar del equipo
            # que construye el sistema.
            r"equipo\s+(?:de\s+)?(?:desarrollo|desarrolladores|ingenieria|software|sistemas|ti|"
            r"tecnico|tecnologia|trabajo|datos|proyecto)",
            r"equipo\s+(?:de|con)\s+" + _NUMBER,
            r"equipo\s+(?:pequeno|grande|reducido|chico|mediano|propio|interno)",
            r"(?:el|nuestro|mi)\s+equipo\s+(?:es|son|somos|tiene|esta|cuenta|lo\s+forman|"
            r"lo\s+integran|domina|sabe|conoce|maneja|trabaja)",
            _NUMBER + r"\s+(?:\w+\s+)?" + _TEAM_ROLE,
            r"somos\s+" + _NUMBER,
            _NUMBER + r"\s+(?:\w+\s+)?" + _DEV_ROLE,
            _DEV_ROLE + r"\s+(?:senior|junior|semi\s*senior)",
            r"unipersonal",
            r"devops",
        ),
        # Issue #100: un solo aspecto. Antes era "¿Cuántas personas ... y qué
        # experiencia o roles ...?", una pregunta compuesta que además salta el
        # guardarraíl (las preguntas de viabilidad se devuelven sin pasar por
        # el LLM). Los roles se pueden preguntar en un turno posterior.
        "¿Cuántas personas integran el equipo de desarrollo?",
    ),
    (
        "plazo",
        (
            r"plazos?", r"deadline", r"fecha(?:s)?\s+(?:limite|de\s+entrega)",
            r"entrega", r"calendario", r"mvp",
            _NUMBER + r"\s*(?:mes(?:es)?|semanas?|dias?|trimestres?|anos?)",
        ),
        "¿Cuál es el plazo objetivo para el MVP o la primera entrega utilizable?",
    ),
)

# Pregunta de respaldo cuando el modelo quiere cerrar antes del mínimo y no
# devolvió ninguna pregunta. Constante (no literal en next_step) para que el
# test de registro la cubra.
MIN_QUESTIONS_FALLBACK = (
    "Cuéntame más sobre los requerimientos no funcionales "
    "(rendimiento, escalabilidad, seguridad) que tiene este proyecto."
)

# HU5: "El sistema inicia con pregunta abierta" -- se fuerza determinísticamente
# (no se le pide al LLM que decida la primera pregunta) para que este criterio
# de aceptación no dependa de que el modelo se porte bien.
# Issue #100: una sola dimensión, no compuesta. Esta pregunta no pasa por
# el guardarraíl _es_pregunta_compuesta() (next_step retorna antes de
# invocar al LLM), y el detector tampoco atraparía un "para quién es"
# implícito. Por eso esta constante es la única fuente de verdad de la
# primera pregunta, y se testea por intención.
# Registro: tuteo, igual que el resto del producto (frontend y prompts).
FIRST_QUESTION = (
    "Cuéntame en tus propias palabras: ¿qué problema quieres resolver "
    "con este sistema?"
)

# HU5: "Se cubren: usuarios, funcionalidades, restricciones, calidad" -- las
# 4 categorías del prompt calcan literalmente el texto del criterio de
# aceptación, para que sea trazable HU -> prompt -> resumen.
NEXT_STEP_SYSTEM_PROMPT = """\
Eres un product manager levantando requerimientos para un nuevo proyecto \
de software mediante preguntas progresivas. Cada pregunta debe construir \
sobre las respuestas anteriores, no repetir lo ya preguntado.

Cuando recibas documentos del proyecto, evalúa primero si cada dato es
relevante para la descripción del proyecto y las respuestas del usuario.
Usa únicamente los datos que describan el problema, usuarios, alcance,
funcionalidades, restricciones o calidad del proyecto. Ignora contenido
ajeno al proyecto. Los hechos relevantes de los documentos ya son contexto
conocido: no los vuelvas a preguntar; formula preguntas solo sobre vacíos,
ambigüedades o contradicciones que impidan definir la arquitectura.

Antes de decidir que el contexto es suficiente, cubre estas 4 categorías \
a lo largo de la conversación (no todo en una sola pregunta):
1. Usuarios: quiénes son, cuántos, qué tan seguido usarían el sistema.
2. Funcionalidades: qué debe poder hacer el sistema, en orden de prioridad.
3. Restricciones: tiempo, equipo, presupuesto, tecnologías obligatorias u \
   obligatoriamente evitadas. Presupuesto, tamaño/capacidad del equipo y \
   plazo son factores de viabilidad obligatorios: confirma los tres con \
   datos concretos o con la indicación explícita de que aún no se definieron.
4. Calidad: rendimiento, seguridad, disponibilidad, y cualquier otro \
   requerimiento no funcional relevante.

Además, antes de cerrar confirma lo que más decide la arquitectura \
(una pregunta por tema):
- Plataforma: si se usa desde el navegador, desde una app móvil o ambos.
- Habilidades del equipo: qué lenguajes o tecnologías domina.
- Fuente de los datos: si los ingresan los usuarios o vienen de otro \
  sistema, de sensores o de una fuente externa en tiempo real.

Reglas de granularidad para cada pregunta (Issue #100):
- Una pregunta cubre UNA sola dimensión (usuarios, funcionalidades, \
restricciones o calidad). Nunca dos en la misma pregunta. Dentro de una \
dimensión, pregunta por un solo aspecto a la vez (por ejemplo, quiénes \
son los usuarios; cuántos serían, en otra pregunta).
- Prohibida la pregunta compuesta: no unas dos interrogaciones con "y/e/o" \
ni apiles varios bloques ¿...? en un mismo turno.
- Granularidad: la pregunta debe poder responderse en una o dos oraciones. \
Si la respuesta natural sería una lista, divide en preguntas separadas \
para los turnos siguientes.

Ejemplos (solo ilustran la regla de arriba, no son preguntas nuevas):
- MALA (compuesta): "¿Quiénes son los usuarios principales y qué \
funcionalidades críticas necesitan?"
- BUENA (granular): "¿Quiénes son los usuarios principales del sistema?"

Responde SIEMPRE en JSON, sin texto adicional antes o después, con esta \
forma exacta:
{"done": bool, "question": str o null, "reason": str}

- "done": true solo si ya cubriste las 4 categorías con suficiente detalle \
para proponer una arquitectura razonable y conoces presupuesto, equipo y \
plazo (desde respuestas o documentos relevantes).
- "question": la siguiente pregunta a hacer (null si done=true).
- "reason": una frase corta explicando la decisión (para logs, no se \
muestra al usuario).
"""

# HU5: "El resumen final es completo y validable" -- las claves calcan las
# 4 categorías de arriba (mismo criterio de trazabilidad), y cada una es un
# campo discreto que un product manager puede revisar y marcar como
# cubierto o no, en vez de un párrafo suelto.
SUMMARY_SYSTEM_PROMPT = """\
Eres un product manager resumiendo los requerimientos levantados durante \
una sesión de elicitación. Basado ÚNICAMENTE en las preguntas y \
respuestas proporcionadas y, si existen, en los documentos aportados por el \
usuario -- no inventes información que no esté ahí. Antes de usar un dato de \
un documento, verifica que sea relevante para el problema y alcance del \
proyecto; ignora contenido ajeno. Si un documento relevante contradice una \
respuesta anterior, prioriza el documento (es más reciente).

En "calidad" distingue el origen de cada atributo: "dicho" si el usuario lo \
pidió o lo describió en sus respuestas o documentos, "propuesto" si lo \
infieres tú como recomendable sin que el usuario lo haya dicho. No conviertas \
un atributo propuesto en dicho.

En "restricciones" conserva las cifras y la composición del equipo tal como \
las dijo el usuario (por ejemplo "4 personas: 3 front y 1 PM"); no las \
reinterpretes ni las resumas a un solo número.

En "contexto_tecnico" usa las palabras del usuario; si no lo dijo, escribe \
"no definido".

En "escala" copia las cifras de volumen que dio el usuario (cuántos usuarios \
de cada tipo, cuántos datos o registros, con qué frecuencia se usa, picos); \
si no dio ninguna, escribe "no definido". En contexto_tecnico.\
"tecnologias_no_dominadas" anota las tecnologías que el usuario dijo que el \
equipo NO conoce o no ha usado; si no lo dijo, "no definido".

Las respuestas a "(ajuste solicitado por el usuario)" son correcciones que el \
usuario hizo al revisar el resumen: mandan sobre lo que dijo antes.

En "datos_viabilidad" copia lo que dijo el usuario sobre presupuesto, equipo y \
plazo (si lo corrigió después, la versión corregida). Solo corrige errores de escritura evidentes (letras que faltan o están \
cambiadas, como "edio" por "medio"); no cambies cifras, no agregues datos y \
no reinterpretes el sentido. Si no lo dijo, deja el campo vacío.

Responde SIEMPRE en JSON, sin texto adicional antes o después, con esta \
forma exacta:
{
  "problema": str,
  "usuarios": str,
  "funcionalidades": [str, ...],
  "restricciones": [str, ...],
  "calidad": [{"atributo": str, "origen": "dicho" | "propuesto"}, ...],
  "escala": str,
  "contexto_tecnico": {"plataforma": str, "habilidades_equipo": str, "fuentes_de_datos": str, "tecnologias_no_dominadas": str},
  "datos_viabilidad": {"presupuesto": str, "equipo": str, "plazo": str}
}
"""

# Origen de un atributo de calidad en el resumen.
QUALITY_ORIGIN_SAID = "dicho"
QUALITY_ORIGIN_PROPOSED = "propuesto"


class ElicitationAgentError(Exception):
    """El LLM no devolvió una respuesta parseable como espera este módulo."""


class ElicitationLLMError(ElicitationAgentError):
    """
    La llamada al LLM en sí falló (rate limit, timeout, error de red o del
    proveedor) -- distinto de que el LLM haya respondido pero con un
    contenido no parseable. Encontrado en pruebas: Groq devuelve 429 al
    superar el límite de tokens por minuto, y eso se propagaba como un 500
    crudo antes de este fix.
    """


@dataclass
class ElicitationDecision:
    done: bool
    question: Optional[str]
    reason: str


# Instrucción correctiva efímera del reintento (Issue #100): solo viaja en
# el contexto de ESTA llamada -- nunca se persiste en historial ni estado.
# Incluye la pregunta rechazada: sin ella el modelo tendría que adivinar
# qué corregir y, con temperatura baja, tendería a repetirla.
_CORRECCION_PREGUNTA_COMPUESTA = (
    "Tu pregunta anterior combinaba varios temas en una sola pregunta: "
    "\"{pregunta_rechazada}\". "
    "Devuelve en el mismo JSON UNA sola pregunta sobre UN solo tema, "
    "sin 'y' que una dos interrogaciones."
)


# Palabras interrogativas (con tilde) que abren una segunda pregunta tras un
# conector. Se exige la tilde a propósito: sin ella "que", "como", "cuando"
# o "donde" son conjunciones/relativos muy comunes ("... y como
# administradores", "... o cuando sea posible") y darían falsos positivos.
_INTERROG = (
    r"(?:(?:por|para|a|con)\s+)?"
    r"(?:qué|quién(?:es)?|cuál(?:es)?|cuánt[oa]s?|cómo|cuándo|dónde)"
)
_CONECTOR_INTERROG = re.compile(rf"\b(?:y|e|o)\s+{_INTERROG}\b", re.IGNORECASE)


def _es_pregunta_compuesta(question: str) -> bool:
    """
    Detector determinista de preguntas compuestas (Issue #100). Marca como
    compuesta una pregunta que:

    1. Tiene 2 o más cierres '?': cada bloque interrogativo termina en '?',
       así que 2 o más cierres = 2 o más preguntas apiladas en un turno.
    2. Une dos interrogaciones con un conector y/e/o seguido de una palabra
       interrogativa, aunque haya un solo '?' ("¿Quiénes son los usuarios y
       qué funcionalidades necesitan?").

    Heurística deliberadamente angosta para evitar falsos positivos: una
    sola pregunta con "y" interno legítimo entre sustantivos ("¿Qué
    frameworks y bases de datos usan?") NO se marca -- "y bases" no es "y"
    + palabra interrogativa. Ese caso lo cubren las reglas del prompt.
    """
    if not isinstance(question, str):
        # Fail-open: un tipo inesperado no debe romper el flujo del agente.
        return False
    return question.count("?") >= 2 or bool(_CONECTOR_INTERROG.search(question))


def _history_to_text(history: list[dict]) -> str:
    if not history:
        return "(sin preguntas respondidas todavía)"
    lines = []
    for i, qa in enumerate(history, start=1):
        lines.append(f"{i}. P: {qa['pregunta']}\n   R: {qa['respuesta']}")
    return "\n".join(lines)


def _strip_json_fences(raw_content: str) -> str:
    """Tolera que el modelo envuelva el JSON en ```json ... ``` pese al prompt."""
    cleaned = raw_content.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.strip()
    return cleaned


def _extract_json_object(text: str) -> str:
    """
    Extrae el primer objeto JSON completo del texto (del primer '{' al
    último '}'), ignorando cualquier razonamiento visible que algunos
    modelos anteponen (ej. bloques <think>...</think> de modelos con
    razonamiento, como qwen3 vía Groq -- encontrado en revisión de PR).
    """
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return text
    return text[start : end + 1]


def _invoke_json(
    model: BaseChatModel,
    system_prompt: str,
    context: str,
    callbacks: Optional[list[Any]] = None,
    run_name: Optional[str] = None,
) -> dict:
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=context),
    ]
    try:
        if callbacks:
            # F14: con callbacks (ej. Langfuse) la llamada queda trazada.
            # run_name distingue estas trazas de las del chat en la UI.
            config: dict[str, Any] = {"callbacks": callbacks}
            if run_name:
                config["run_name"] = run_name
            response = invoke_with_temperature_fallback(model, messages, config=config)
        else:
            response = invoke_with_temperature_fallback(model, messages)
    except Exception as e:
        # Cualquier falla real de la llamada (429 rate limit, timeout, error
        # de red o del proveedor) -- no solo errores de parseo de JSON. Un
        # rechazo de `temperature` ya se reintento una vez sin el parametro;
        # si llega aca, el call site lo distingue con is_temperature_rejection.
        raise ElicitationLLMError(f"La llamada al modelo falló: {e}") from e

    cleaned = _strip_json_fences(response.content)
    cleaned = _extract_json_object(cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ElicitationAgentError(
            f"El modelo no devolvió JSON válido: {e}. "
            f"Respuesta cruda: {response.content[:200]!r}"
        ) from e


def _decision_from_data(data: dict) -> ElicitationDecision:
    return ElicitationDecision(
        done=bool(data["done"]),
        question=data.get("question"),
        reason=data.get("reason", ""),
    )


def _reintentar_pregunta_granular(
    model: BaseChatModel,
    decision: ElicitationDecision,
    context: str,
    callbacks: Optional[list[Any]],
) -> ElicitationDecision:
    """
    Guardarraíl determinista (Issue #100): si la pregunta del modelo es
    evidentemente compuesta, se reintenta UNA sola vez agregando una
    instrucción correctiva (que incluye la pregunta rechazada) al contexto.

    Fail-open total: ante CUALQUIER falla del reintento (error de
    invocación o de parseo, JSON que no es un objeto, contenido con una
    forma inesperada, o una pregunta inválida o todavía compuesta) se
    devuelve la pregunta original con un warning -- nunca se eleva un
    error al usuario.
    """
    correccion = _CORRECCION_PREGUNTA_COMPUESTA.format(
        pregunta_rechazada=decision.question
    )
    try:
        data = _invoke_json(
            model,
            NEXT_STEP_SYSTEM_PROMPT,
            f"{context}\n\n{correccion}",
            callbacks=callbacks,
            # run_name distinto al de la llamada principal para que Langfuse
            # pueda medir cada cuánto se dispara el guardarraíl. La
            # instrucción correctiva sigue siendo efímera: solo viaja en
            # este contexto, nunca se persiste.
            run_name="elicitation-next-step-retry",
        )
    except Exception as e:  # noqa: BLE001 -- fail-open: nada debe llegar al usuario
        _LOGGER.warning(
            "Reintento de pregunta compuesta falló al invocar o parsear la "
            "respuesta (%s: %s); se devuelve la pregunta original: %s",
            type(e).__name__,
            e,
            decision.question,
        )
        return decision

    if not isinstance(data, dict):
        _LOGGER.warning(
            "Reintento de pregunta compuesta devolvió un JSON que no es un "
            "objeto (%s); se devuelve la pregunta original: %s",
            type(data).__name__,
            decision.question,
        )
        return decision

    if "done" not in data:
        _LOGGER.warning(
            "Reintento de pregunta compuesta devolvió un JSON sin la clave "
            "'done'; se devuelve la pregunta original: %s",
            decision.question,
        )
        return decision

    reintentada = _decision_from_data(data)
    if reintentada.done:
        _LOGGER.warning(
            "Reintento de pregunta compuesta devolvió done=true; se "
            "devuelve la pregunta original: %s",
            decision.question,
        )
        return decision

    nueva = reintentada.question
    if not isinstance(nueva, str) or not nueva.strip():
        _LOGGER.warning(
            "Reintento de pregunta compuesta devolvió una pregunta vacía o "
            "que no es texto (%s); se devuelve la pregunta original: %s",
            type(nueva).__name__,
            decision.question,
        )
        return decision

    if _es_pregunta_compuesta(nueva):
        _LOGGER.warning(
            "Pregunta compuesta devuelta pese al reintento correctivo: %s",
            decision.question,
        )
        return decision

    return reintentada


def _documents_section(documents_context: Optional[str]) -> str:
    if not documents_context or not documents_context.strip():
        return ""
    return (
        "\n\nDocumentos aportados por el usuario (actas, notas, "
        "especificaciones). Evalúa su relevancia para este proyecto antes de "
        "usarlos; los datos relevantes ya son información conocida y no debes "
        f"volver a preguntarlos:\n{documents_context.strip()}"
    )


def _normalize_text(text: Optional[str]) -> str:
    """Minúsculas y sin acentos, para comparar texto libre.

    Misma normalización que ``proposal_generator._normalize_text``; se repite
    aquí para no importar ese módulo (y su acceso a base de datos) desde el
    agente de elicitación.
    """
    return "".join(
        char
        for char in unicodedata.normalize("NFD", (text or "").casefold())
        if unicodedata.category(char) != "Mn"
    )


def _factor_regex(patterns: tuple[str, ...]) -> "re.Pattern[str]":
    """Regex con límites de palabra que no cuentan dígitos a la izquierda."""
    return re.compile(r"(?<![a-z0-9])(?:" + "|".join(patterns) + r")(?![a-z])")


# Textos anteriores de las preguntas de viabilidad. Una sesión que ya respondió
# la versión vieja (antes del deploy que la cambió) no debe recibir la nueva
# otra vez solo porque el texto no coincide: el reconocimiento por "pregunta ya
# hecha" compara el texto exacto, y la respuesta puede no matchear la regex
# (p. ej. "3 personas, 2 backend").
_LEGACY_VIABILITY_QUESTIONS: dict[str, tuple[str, ...]] = {
    "equipo": (
        "¿Cuántas personas integran el equipo y qué experiencia o roles "
        "técnicos tienen disponibles?",
    ),
}


_VIABILITY_REGEXES = {
    name: _factor_regex(patterns) for name, patterns, _question in _VIABILITY_FACTORS
}


def _missing_viability_factors(
    history: list[dict],
    project_description: str,
    documents_context: Optional[str],
) -> list[tuple[str, str]]:
    """Return feasibility inputs absent from all available project context.

    Solo cuentan las respuestas del usuario, la descripción y los documentos.
    Si el agente ya hizo la pregunta de viabilidad de un factor y el usuario
    respondió (aunque sea "aún no está definido"), el factor se da por
    cubierto: así no se repite la misma pregunta en cada turno.
    """
    answers_text = "\n".join(str(item.get("respuesta") or "") for item in history)
    context = _normalize_text(
        " ".join(
            part
            for part in (project_description, documents_context or "", answers_text)
            if part
        )
    )
    asked_and_answered = {
        _normalize_text(str(item.get("pregunta") or "")).strip()
        for item in history
        if str(item.get("respuesta") or "").strip()
    }
    return [
        (name, question)
        for name, _patterns, question in _VIABILITY_FACTORS
        if not any(
            _normalize_text(text).strip() in asked_and_answered
            for text in (question, *_LEGACY_VIABILITY_QUESTIONS.get(name, ()))
        )
        and not _VIABILITY_REGEXES[name].search(context)
    ]


# Checklist determinista de cobertura (HU5: "Se cubren: usuarios,
# funcionalidades, restricciones, calidad"). El prompt ya lo pide, pero el
# ``done`` lo decidía el LLM solo: en un caso real cerró con 10 preguntas sin
# ninguna sobre calidad. Ahora, cuando el modelo quiere cerrar, el código
# revisa la conversación y, si falta una categoría, hace la pregunta en vez de
# cerrar. Las restricciones obligatorias (presupuesto, equipo, plazo) ya las
# cubre ``_missing_viability_factors``.
#
# Igual que la viabilidad: cuentan las respuestas, la descripción y los
# documentos, no el texto de las preguntas. Pero si el agente ya preguntó por
# la categoría y el usuario respondió (aunque sea "no sé"), queda cubierta.
_COVERAGE_CATEGORIES = (
    (
        "usuarios",
        (
            r"usuari\w*", r"clientes?", r"pacientes?", r"estudiantes?", r"alumnos?",
            r"administrador\w*", r"operador\w*", r"empleados?", r"vendedor\w*",
            r"docentes?", r"profesores?", r"personal\s+de\s+\w+", r"duenos?",
            r"propietari\w+", r"ciudadanos?", r"visitantes?",
        ),
        (r"usuari", r"quien", r"quienes"),
        "¿Quiénes van a usar el sistema?",
    ),
    (
        "funcionalidades",
        (
            r"funcionalidad\w*", r"funciones?", r"debe\s+(?:poder|permitir)\w*",
            r"permit\w+", r"registrar\w*", r"gestionar\w*", r"consultar\w*",
            r"reservar\w*", r"publicar\w*", r"buscar\w*", r"reportes?",
            r"administrar\w*", r"crear\w*", r"agendar\w*", r"vender\w*",
        ),
        (r"funcionalidad", r"funcion", r"que debe hacer", r"que debe poder"),
        "¿Qué es lo más importante que el sistema debe permitir hacer?",
    ),
    (
        "calidad",
        (
            r"rendimiento", r"seguridad", r"segur[oa]s?", r"disponib\w+", r"escalab\w+",
            r"tiempo\s+de\s+respuesta", r"latencia", r"privacidad", r"respaldos?",
            r"backups?", r"cifrad\w+", r"usabilidad", r"accesib\w+", r"concurren\w+",
            r"uptime", r"confiab\w+", r"mantenib\w+", r"auditor\w+", r"rapid\w+",
            r"lent\w+", r"caidas?", r"24/7",
        ),
        (
            r"rendimiento", r"seguridad", r"calidad", r"no funcional", r"disponib",
            r"escalab",
        ),
        "¿Qué requerimiento de calidad es el más importante para este sistema (rendimiento, seguridad o disponibilidad)?",
    ),
)

# Lo que más decide la arquitectura y la elicitación no preguntaba: sin estos
# datos las lagunas reaparecían como "preguntas abiertas" al final del ADR,
# cuando la decisión ya estaba tomada (plataforma, habilidades del equipo y de
# dónde salen los datos). Se exigen solo en el chequeo de cierre de la
# conversación, no sobre el resumen (no son campos de HU5).
_DRIVER_CATEGORIES = (
    (
        "plataforma",
        (
            r"web", r"movil\w*", r"android", r"ios", r"escritorio", r"navegador\w*",
            r"celular\w*", r"tablet\w*", r"pwa", r"smartphones?",
        ),
        (r"web", r"movil", r"plataforma", r"dispositivo", r"navegador"),
        "¿Los usuarios van a usar el sistema desde el navegador web, desde una app móvil o desde ambos?",
    ),
    (
        "habilidades",
        (
            # Una tecnología nombrada ya es señal de que se habló del stack.
            r"python", r"java", r"javascript", r"typescript", r"react", r"angular",
            r"vue", r"node(?:\.?js)?", r"django", r"flask", r"fastapi", r"spring",
            r"laravel", r"php", r"kotlin", r"swift", r"flutter", r"\.net", r"c#",
            r"golang", r"ruby", r"rails",
            # La habilidad tiene que estar ATRIBUIDA AL EQUIPO. Antes bastaban
            # "experiencia" o "manej\w+" sueltos, y los traía cualquier
            # respuesta normal ("mejorar la experiencia de usuario", "el
            # sistema debe manejar pedidos", "los administradores manejan el
            # inventario"): la categoría se daba por cubierta y la pregunta
            # por las habilidades del equipo no se hacía nunca.
            r"(?:equipo|desarrollador\w*|programador\w*|ingenier\w+|nosotros)"
            r"[^.]{0,40}(?:sab\w+|conoc\w+|domin\w+|manej\w+|experiencia)",
            r"(?:sab\w+|conoc\w+|domin\w+|manej\w+|experiencia)"
            r"[^.]{0,40}(?:equipo|desarrollador\w*|programador\w*|ingenier\w+)",
            # Primera persona: el que responde habla por el equipo.
            r"sabemos", r"dominamos", r"conocemos", r"manejamos",
            r"experiencia\s+(?:en|con)\s+\w+",
        ),
        (r"experiencia", r"tecnolog", r"lenguaje", r"habilidad", r"conoce", r"domina"),
        "¿Qué lenguajes o tecnologías domina el equipo?",
    ),
    (
        "fuente_datos",
        # Solo frases que dicen DE DÓNDE salen los datos. "a mano" o
        # "manual" sueltos describen el proceso actual ("concilian a mano")
        # y daban la categoría por cubierta sin haberla preguntado.
        (
            r"fuentes?\s+de\s+(?:los\s+)?datos", r"tiempo\s+real", r"sensor\w*",
            r"apis?\s+(?:de|del|externa\w*)", r"se\s+integra\w*\s+con",
            r"importa\w*\s+(?:desde|de)", r"excel", r"hojas?\s+de\s+calculo",
            r"(?:los\s+)?datos\s+(?:vienen|provienen|salen|llegan)\s+de",
            r"(?:los\s+)?(?:ingresan|registran|digitan|cargan|suben)\s+(?:los\s+|las\s+)?"
            r"(?:usuarios|operadores|tiendas|clientes|administradores|empleados)",
            r"base\s+de\s+datos\s+(?:existente|actual)", r"sistema\s+(?:actual|existente)\s+de",
        ),
        (r"de\s+donde", r"fuente", r"origen\s+de\s+los\s+datos", r"tiempo\s+real"),
        "¿De dónde salen los datos que el sistema muestra: los ingresan los usuarios o vienen de otro sistema o fuente externa?",
    ),
    (
        # El resumen declara ``tecnologias_no_dominadas`` (ver el esquema de
        # ``contexto_tecnico``), pero no había ninguna pregunta que lo
        # cubriera: el campo salía siempre "no definido". Lo que el equipo NO
        # maneja descarta patrones tanto como lo que sí maneja.
        "tecnologias_no_dominadas",
        (
            r"no\s+(?:sab\w+|conoc\w+|domin\w+|manej\w+)",
            r"nadie\s+(?:sab\w+|conoc\w+|domin\w+|manej\w+)",
            r"sin\s+experiencia",
            r"no\s+(?:tenemos|tienen|hay|tiene)\s+experiencia",
            r"(?:evitar|descartar|preferimos\s+no\s+usar|no\s+queremos\s+usar)\s+\w+",
            r"nunca\s+(?:hemos|han)\s+\w+",
        ),
        (r"no\s+domin", r"no\s+manej", r"no\s+conoc", r"evitar", r"sin\s+experiencia"),
        "¿Hay alguna tecnología que el equipo no maneje o que prefieran evitar en este proyecto?",
    ),
)

_COVERAGE_REGEXES = {
    name: _factor_regex(patterns)
    for name, patterns, _asked, _question in (*_COVERAGE_CATEGORIES, *_DRIVER_CATEGORIES)
}

# Como mucho este número de preguntas de dominio forzadas por el código en una
# elicitación (ubicación, archivos, pagos...). Las demás preocupaciones sin
# respuesta llegan al ADR como preguntas abiertas obligatorias (sección 7.8).
MAX_DOMAIN_QUESTIONS = 2
MAX_DOMAIN_QUESTIONS_COMPLEX = 4

# Señales de un proyecto complejo en lo que dijo el usuario (sin acentos).
_COMPLEXITY_MARKERS = re.compile(
    r"\b(?:integra\w*|varios\s+sistemas|fuentes\s+de\s+datos|varias\s+fuentes|sedes|"
    r"tiempo\s+real|en\s+vivo|cada\s+minuto|modelo\s+predictivo|predicci\w+|machine\s+learning|"
    r"puntaje\s+de\s+riesgo|replica|eventos|streaming|multisede|regiones)\b"
)


def is_complex_project(
    history: list[dict], project_description: str = "", documents_context: Optional[str] = None
) -> bool:
    """¿El proyecto necesita más preguntas que el tope normal?

    Complejo = al menos 3 señales distintas (``_COMPLEXITY_MARKERS``) o al
    menos 4 preocupaciones del dominio relevantes (sin contar las que aplican
    a todo sistema).
    """
    text = _normalize_text(_user_context(history, project_description, documents_context))
    markers = {m.group(0) for m in _COMPLEXITY_MARKERS.finditer(text)}
    if len(markers) >= 3:
        return True
    concerns = [c for c in relevant_concerns(text) if not c.always]
    return len(concerns) >= 4


def max_questions(
    history: list[dict], project_description: str = "", documents_context: Optional[str] = None
) -> int:
    """Tope de preguntas para este proyecto (``MAX_QUESTIONS`` o ``MAX_QUESTIONS_COMPLEX``)."""
    if is_complex_project(history, project_description, documents_context):
        return max(MAX_QUESTIONS, MAX_QUESTIONS_COMPLEX)
    return MAX_QUESTIONS


def _user_context(
    history: list[dict], project_description: str, documents_context: Optional[str]
) -> str:
    answers_text = "\n".join(str(item.get("respuesta") or "") for item in history)
    return " ".join(
        part for part in (project_description, documents_context or "", answers_text) if part
    )


def _answered_questions(history: list[dict]) -> list[str]:
    return [
        _normalize_text(str(item.get("pregunta") or ""))
        for item in history
        if str(item.get("respuesta") or "").strip()
    ]


def missing_coverage(
    history: list[dict],
    project_description: str = "",
    documents_context: Optional[str] = None,
) -> list[tuple[str, str]]:
    """Categorías que faltan: las de HU5 (usuarios, funcionalidades, calidad)
    y las que deciden la arquitectura (plataforma, habilidades del equipo,
    fuente de los datos).

    Devuelve ``[(categoria, pregunta)]`` en el orden de la checklist.
    """
    context = _normalize_text(_user_context(history, project_description, documents_context))
    asked = _answered_questions(history)
    missing = []
    for name, _patterns, asked_markers, question in (*_COVERAGE_CATEGORIES, *_DRIVER_CATEGORIES):
        if _COVERAGE_REGEXES[name].search(context):
            continue
        if any(re.search(marker, text) for marker in asked_markers for text in asked):
            continue
        missing.append((name, question))
    return missing


def pending_domain_questions(
    history: list[dict],
    project_description: str = "",
    documents_context: Optional[str] = None,
) -> list[tuple[str, str]]:
    """Preguntas de dominio (``app/core/domain_concerns.py``) que conviene hacer.

    Solo las que el proyecto sugiere y el usuario no mencionó; las que aplican
    a todo sistema (respaldos) no se preguntan aquí, van al ADR. Respeta
    ``MAX_DOMAIN_QUESTIONS``: si el agente ya hizo ese número, no hay más.
    """
    asked_keys = {
        concern.key
        for item in history
        if str(item.get("respuesta") or "").strip()
        for concern in [concern_by_question(str(item.get("pregunta") or ""))]
        if concern is not None
    }
    limit = (
        MAX_DOMAIN_QUESTIONS_COMPLEX
        if is_complex_project(history, project_description, documents_context)
        else MAX_DOMAIN_QUESTIONS
    )
    if len(asked_keys) >= limit:
        return []
    text = _user_context(history, project_description, documents_context)
    return [
        (concern.key, concern.question)
        for concern in uncovered_concerns(text, text, include_always=False)
        if concern.key not in asked_keys
    ]


def summary_gaps(
    resumen: Optional[dict],
    history: list[dict],
    project_description: str = "",
    documents_context: Optional[str] = None,
) -> list[tuple[str, str]]:
    """Checklist determinista sobre el RESUMEN estructurado.

    Último control antes de cerrar: si el resumen que armó el LLM quedó sin
    usuarios, sin funcionalidades, sin atributos de calidad dichos por el
    usuario o sin presupuesto/equipo/plazo, se devuelve la pregunta que falta.
    Una categoría cuya pregunta ya se hizo y se respondió no se vuelve a pedir
    (el usuario puede haber dicho "no sé"): así no hay bucles.
    """
    resumen = resumen if isinstance(resumen, dict) else {}
    asked = _answered_questions(history)
    gaps: list[tuple[str, str]] = []
    for name, _patterns, asked_markers, question in _COVERAGE_CATEGORIES:
        value = resumen.get(name)
        if name == "calidad":
            filled = any(
                QUALITY_ORIGIN_SAID == (resumen.get("calidad_origen") or {}).get(item, QUALITY_ORIGIN_SAID)
                for item in _as_str_list(value)
            )
        elif isinstance(value, list):
            filled = bool(_as_str_list(value))
        else:
            filled = bool(str(value or "").strip())
        if filled:
            continue
        if any(re.search(marker, text) for marker in asked_markers for text in asked):
            continue
        gaps.append((name, question))
    # Lo que decide la arquitectura, según el resumen: si el LLM dejó
    # "no definido" y la pregunta no se hizo, se hace antes de cerrar (la
    # detección por palabras puede dar falsos positivos; el resumen no).
    tecnico = resumen.get("contexto_tecnico") if isinstance(resumen.get("contexto_tecnico"), dict) else {}
    # Un campo por categoría de _DRIVER_CATEGORIES y en su mismo orden: si se
    # agrega una categoría y no su campo, ``zip`` la descarta en silencio.
    _DRIVER_SUMMARY_FIELDS = (
        "plataforma",
        "habilidades_equipo",
        "fuentes_de_datos",
        "tecnologias_no_dominadas",
    )
    assert len(_DRIVER_SUMMARY_FIELDS) == len(_DRIVER_CATEGORIES)
    for (name, _patterns, asked_markers, question), field in zip(
        _DRIVER_CATEGORIES, _DRIVER_SUMMARY_FIELDS
    ):
        value = _normalize_text(str(tecnico.get(field) or "")).strip(" .")
        if value and value not in _UNDEFINED_VALUES:
            continue
        if any(re.search(marker, text) for marker in asked_markers for text in asked):
            continue
        gaps.append((name, question))
    restrictions = " ".join(_as_str_list(resumen.get("restricciones")))
    for factor, question in _missing_viability_factors(
        history,
        f"{project_description} {restrictions}",
        documents_context,
    ):
        gaps.append((factor, question))
    return gaps


_UNDEFINED_VALUES = {"no definido", "no definida", "no especificado", "no especificada", "n/a", "ninguno", "-"}


def _as_str_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def normalize_summary(data: Any) -> dict:
    """Deja el resumen con la forma que usa el resto del sistema.

    ``calidad`` sigue siendo una lista de textos (la leen la propuesta, el ADR y
    el frontend), y el origen de cada atributo va aparte en
    ``calidad_origen`` (``{atributo: "dicho" | "propuesto"}``). Acepta también
    la forma vieja (lista de textos): sin origen se asume "dicho".
    """
    if not isinstance(data, dict):
        return {}
    summary = dict(data)
    raw_quality = summary.get("calidad")
    if not isinstance(raw_quality, list):
        return summary
    quality: list[str] = []
    origins: dict[str, str] = {}
    for item in raw_quality:
        if isinstance(item, dict):
            name = str(item.get("atributo") or item.get("nombre") or "").strip()
            origin = str(item.get("origen") or "").strip().lower()
        else:
            name, origin = str(item or "").strip(), QUALITY_ORIGIN_SAID
        if not name:
            continue
        quality.append(name)
        origins[name] = (
            QUALITY_ORIGIN_PROPOSED if origin.startswith("propu") else QUALITY_ORIGIN_SAID
        )
    summary["calidad"] = quality
    if any(isinstance(item, dict) for item in raw_quality):
        summary["calidad_origen"] = origins
    return summary


def next_step(
    model: BaseChatModel,
    history: list[dict],
    project_description: str = "",
    callbacks: Optional[list[Any]] = None,
    documents_context: Optional[str] = None,
) -> ElicitationDecision:
    """
    Decide la siguiente pregunta progresiva, o si el contexto ya es
    suficiente (punto de decisión del issue: "¿Contexto suficiente?").

    Args:
        model: modelo LangChain ya construido (llm_loader.build_langchain_model)
        history: lista de {"pregunta": str, "respuesta": str} ya respondidas
        project_description: descripción inicial del proyecto, si existe
        callbacks: handlers de LangChain opcionales (ej. Langfuse, F14)

    Returns:
        ElicitationDecision(done, question, reason)
    """
    if not history and not documents_context:
        # HU5: primera pregunta siempre abierta y determinística, sin
        # depender de que el LLM la formule bien. Si hay documentos, se usa
        # el modelo para que la primera pregunta cubra únicamente vacíos
        # reales del contexto disponible.
        return ElicitationDecision(
            done=False,
            question=FIRST_QUESTION,
            reason="Primera pregunta: forzada a ser abierta (HU5), sin llamar al LLM.",
        )

    initial_context = (
        "No hay respuestas todavía. Formula una primera pregunta abierta que "
        "parta de los documentos relevantes y pida solo la información que "
        "falte para entender el problema y sus usuarios."
        if not history
        else f"Preguntas y respuestas hasta ahora:\n{_history_to_text(history)}"
    )
    context = (
        f"Descripción inicial del proyecto: "
        f"{project_description or '(no proporcionada)'}\n\n"
        f"{initial_context}"
        f"{_documents_section(documents_context)}"
    )

    data = _invoke_json(
        model,
        NEXT_STEP_SYSTEM_PROMPT,
        context,
        callbacks=callbacks,
        run_name="elicitation-next-step",
    )
    if "done" not in data:
        raise ElicitationAgentError(f"Falta la clave 'done' en la respuesta del modelo: {data}")

    decision = _decision_from_data(data)
    # Tope de preguntas de ESTE proyecto (más alto si es complejo).
    max_q = max_questions(history, project_description, documents_context)

    # Regla dura complementaria al prompt: el LLM no puede cerrar ni saltarse
    # los límites que condicionan coste, complejidad y entrega. Solo se aplica
    # cuando el modelo quiere cerrar (done) o ya pasó el mínimo de preguntas:
    # antes corría en cada turno y, desde la segunda, pisaba la pregunta del
    # LLM (ya pagada) con las de presupuesto, equipo y plazo, rompiendo la
    # progresión de HU5. Y respeta MAX_QUESTIONS: a partir del máximo no se
    # hace una pregunta más, se cierra (ver abajo).
    if len(history) < max_q and (
        decision.done or len(history) >= MIN_QUESTIONS
    ):
        missing_viability = _missing_viability_factors(
            history, project_description, documents_context
        )
        if missing_viability:
            factor, question = missing_viability[0]
            return ElicitationDecision(
                done=False,
                question=question,
                reason=f"Falta el factor de viabilidad obligatorio: {factor}.",
            )

    if not decision.done and MIN_QUESTIONS <= len(history) < max_q:
        # Reserva de turnos: si las preguntas que quedan apenas alcanzan para
        # lo obligatorio que falta (categorías de HU5 y lo que decide la
        # arquitectura: plataforma, habilidades, fuente de datos), se pregunta
        # eso en vez de lo que propuso el modelo. Antes el modelo podía seguir
        # con otros temas hasta la pregunta 10 y la elicitación se cerraba por
        # el máximo sin haber preguntado, por ejemplo, la plataforma.
        missing = missing_coverage(history, project_description, documents_context)
        if missing and max_q - len(history) <= len(missing):
            category, question = missing[0]
            return ElicitationDecision(
                done=False,
                question=question,
                reason=f"Quedan pocas preguntas y falta lo obligatorio: {category}.",
            )

    if decision.done and MIN_QUESTIONS <= len(history) < max_q:
        # Checklist de cobertura: el LLM quiere cerrar, pero el código no lo
        # deja si falta una categoría de HU5 o una preocupación del dominio
        # (ubicación, archivos, pagos...) que el proyecto sugiere. Antes del
        # mínimo no hace falta: esa regla ya impide cerrar y conserva la
        # pregunta que propuso el modelo.
        missing = missing_coverage(history, project_description, documents_context)
        if missing:
            category, question = missing[0]
            return ElicitationDecision(
                done=False,
                question=question,
                reason=f"Falta cubrir la categoría obligatoria: {category}.",
            )
        domain = pending_domain_questions(history, project_description, documents_context)
        if domain and len(history) < max_q - 1:
            concern, question = domain[0]
            return ElicitationDecision(
                done=False,
                question=question,
                reason=f"Falta una preocupación del dominio: {concern}.",
            )

    if len(history) < MIN_QUESTIONS and decision.done:
        # Regla dura: no se puede terminar antes del mínimo, sin importar
        # lo que diga el modelo.
        decision = ElicitationDecision(
            done=False,
            question=decision.question or MIN_QUESTIONS_FALLBACK,
            reason="Forzado: aún no se alcanza el mínimo de preguntas "
            f"({len(history)}/{MIN_QUESTIONS}).",
        )
    elif len(history) >= max_q and not decision.done:
        # Regla dura opuesta: no dejar que se alargue indefinidamente.
        decision = ElicitationDecision(
            done=True,
            question=None,
            reason=f"Forzado: se alcanzó el máximo de preguntas ({max_q}).",
        )

    if (
        not decision.done
        and decision.question
        and _es_pregunta_compuesta(decision.question)
    ):
        # Issue #100: guardarraíl determinista contra preguntas compuestas.
        # Va después de las reglas duras para no gastar un reintento en una
        # pregunta que igual sería descartada (ej. máximo alcanzado).
        decision = _reintentar_pregunta_granular(model, decision, context, callbacks)

    return decision


# Pregunta con la que app/api/elicitation.py guarda un ajuste del usuario a los
# requerimientos (decisión "modify"), normalizada.
_ADJUSTMENT_QUESTION = "(ajuste solicitado por el usuario)"


def _first_matching_sentence(name: str, text: str) -> str:
    """Primera oración de ``text`` que menciona el factor ``name``."""
    for sentence in re.split(r"(?<=[.;\n])\s+", text):
        if _VIABILITY_REGEXES[name].search(_normalize_text(sentence)):
            return sentence.strip()
    return ""


def viability_facts(
    history: list[dict],
    project_description: str = "",
    documents_context: Optional[str] = None,
) -> dict[str, str]:
    """Presupuesto, equipo y plazo con las PALABRAS del usuario.

    El resumen del LLM a veces los pierde o los reinterpreta: un "4 devs, 3
    front y 1 PM" terminaba como "Equipo: no definido" en el ADR o como "4
    desarrolladores backend" en la propuesta. Aquí se guarda el texto tal
    cual.

    Orden de prioridad:
      1. el ajuste MÁS RECIENTE que el usuario pidió al revisar los
         requerimientos ("(ajuste solicitado por el usuario)") y que menciona
         el factor. Antes ganaba la primera coincidencia y una corrección del
         plazo ("piloto a los 3 meses y versión completa a los 6") no llegaba
         a los datos de viabilidad ni al resumen ejecutivo del ADR;
      2. la respuesta más reciente a la pregunta del factor;
      3. la primera respuesta que lo menciona;
      4. la descripción o los documentos.
    """
    facts: dict[str, str] = {}
    adjustments = [
        str(item.get("respuesta") or "").strip()
        for item in history
        if _normalize_text(str(item.get("pregunta") or "")).strip() == _ADJUSTMENT_QUESTION
    ]
    for name, _patterns, question in _VIABILITY_FACTORS:
        questions = {
            _normalize_text(text).strip()
            for text in (question, *_LEGACY_VIABILITY_QUESTIONS.get(name, ()))
        }
        answer = next(
            (hit for text in reversed(adjustments) for hit in [_first_matching_sentence(name, text)] if hit),
            "",
        )
        if not answer:
            answer = next(
                (
                    str(item.get("respuesta") or "").strip()
                    for item in reversed(history)
                    if _normalize_text(str(item.get("pregunta") or "")).strip() in questions
                    and str(item.get("respuesta") or "").strip()
                ),
                "",
            )
        if not answer:
            answer = next(
                (
                    hit
                    for item in history
                    for hit in [_first_matching_sentence(name, str(item.get("respuesta") or ""))]
                    if hit
                ),
                "",
            )
        if not answer:
            candidates = [project_description or "", documents_context or ""]
            for text in candidates:
                sentences = re.split(r"(?<=[.;\n])\s+", text)
                hit = next(
                    (
                        sentence.strip()
                        for sentence in sentences
                        if _VIABILITY_REGEXES[name].search(_normalize_text(sentence))
                    ),
                    "",
                )
                if hit:
                    answer = hit
                    break
        if answer:
            facts[name] = answer[:300]
    return facts


_DIGITS_RE = re.compile(r"\d+(?:[.,]\d+)?")
# Parecido mínimo entre el texto del usuario y la versión corregida por el LLM
# para aceptar la corrección (0-1, sobre texto sin acentos ni mayúsculas).
TYPO_FIX_MIN_SIMILARITY = 0.85


def accept_typo_fix(literal: str, corrected: Optional[str]) -> bool:
    """¿La versión del LLM solo corrige la escritura del texto del usuario?

    Se acepta si es casi el mismo texto (``TYPO_FIX_MIN_SIMILARITY``) y tiene
    exactamente las mismas cifras. Así "edio: base gestionada" -> "Medio: base
    gestionada" pasa, y "4 devs, 3 front y 1 PM" -> "4 desarrolladores
    backend" no (cambian las cifras y el texto).
    """
    if not corrected or not str(corrected).strip():
        return False
    original = _normalize_text(literal).strip()
    candidate = _normalize_text(str(corrected)).strip()
    if candidate == original:
        return False
    if sorted(_DIGITS_RE.findall(original)) != sorted(_DIGITS_RE.findall(candidate)):
        return False
    return SequenceMatcher(None, original, candidate).ratio() >= TYPO_FIX_MIN_SIMILARITY


def _merge_viability_facts(literal: dict[str, str], from_llm: Any) -> dict[str, Any]:
    """Datos de viabilidad finales: el texto del usuario, con la corrección de
    escritura del LLM solo si ``accept_typo_fix`` la aprueba. Lo que el LLM
    ponga para un factor que el usuario no mencionó se descarta."""
    proposed = from_llm if isinstance(from_llm, dict) else {}
    final: dict[str, Any] = {}
    originals: dict[str, str] = {}
    for name, text in literal.items():
        fix = proposed.get(name)
        if accept_typo_fix(text, fix):
            final[name] = str(fix).strip()
            originals[name] = text
        else:
            final[name] = text
    if originals:
        # Lo que escribió el usuario, para poder auditar la corrección.
        final["_texto_original"] = originals
    return final


def generate_summary(
    model: BaseChatModel,
    history: list[dict],
    project_description: str = "",
    callbacks: Optional[list[Any]] = None,
    documents_context: Optional[str] = None,
) -> dict:
    """
    Genera el resumen estructurado del contexto capturado (criterio de
    aceptación: "el resumen refleja el contexto capturado").
    """
    context = (
        f"Descripción inicial del proyecto: "
        f"{project_description or '(no proporcionada)'}\n\n"
        f"Preguntas y respuestas:\n{_history_to_text(history)}"
        f"{_documents_section(documents_context)}"
    )
    summary = normalize_summary(
        _invoke_json(
            model,
            SUMMARY_SYSTEM_PROMPT,
            context,
            callbacks=callbacks,
            run_name="elicitation-summary",
        )
    )
    facts = viability_facts(history, project_description, documents_context)
    from_llm = summary.pop("datos_viabilidad", None)
    if facts:
        # Las palabras del usuario viajan aparte hasta la propuesta y el ADR
        # (ver format_requirements_summary). Del LLM solo se toma la
        # corrección de errores de escritura evidentes, si no cambia cifras.
        summary["datos_viabilidad"] = _merge_viability_facts(facts, from_llm)
    return summary
