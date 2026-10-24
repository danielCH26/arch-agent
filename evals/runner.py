"""
Harness del golden set: mide la variabilidad real de las propuestas de arquitectura.

El scorer (``score_output``) es determinista y puro: no hace red, no toca la base
de datos y no llama a un LLM. Eso lo hace testeable offline en CI.

El runner de ejecucion arma el prompt con la funcion REAL de produccion
(``app.core.proposal_generator._build_prompt``). Nunca se copia el texto del
prompt aqui: si el prompt de produccion cambia, el golden set se entera solo.
El costo de eso es que ``--dry-run`` y la corrida importan el backend: hace
falta tener instalado ``requirements.txt`` (no hace falta ningun servicio
corriendo: ni Postgres, ni PGVector, ni el modelo de embeddings).

Uso rapido:
    python -m evals.runner --dry-run
    python -m evals.runner --models openai/gpt-oss-120b --repeats 5

Variables de entorno:
    LLM_API_KEY    clave del proveedor. Si falta y el proveedor es el default
                   de la app (Groq), se usa GROQ_API_KEY, igual que produccion.
    LLM_BASE_URL   endpoint OpenAI-compatible. Default: DEFAULT_LLM_BASE_URL.
    LLM_MODEL      modelo si no se pasa --models. Default: DEFAULT_LLM_MODEL.
    LLM_TEMPERATURE  temperatura si no se pasa --temperature, con la misma
                   regla que produccion (llm_temperature()). Default:
                   DEFAULT_LLM_TEMPERATURE.

Exit codes:
    0  la corrida midio y paso el gate (--min-ok-rate, todos los modelos
       construidos, al menos un par (caso, modelo) con metricas).
    1  la corrida no es confiable: ver el motivo impreso al final.
    2  error de uso o de configuracion (flags, variables, --case inexistente).
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import importlib.metadata
import inspect
import itertools
import json
import os
import platform
import re
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

# --- Contrato del prompt de produccion ---------------------------------------
# Las secciones obligatorias son las de PRODUCCION, no una copia local. La copia
# anterior (3 secciones, "Tecnologías" con tilde, comparada sin normalizar
# acentos) se desincronizo del prompt y media como fallida toda propuesta
# valida de produccion (review de #108, lau2413). Se resuelve lazy porque
# importar app.core es caro y el runner debe arrancar rapido en --dry-run.
_SECCIONES_CACHE: tuple[str, ...] | None = None


def _secciones_requeridas() -> tuple[str, ...]:
    """Las secciones obligatorias del prompt, segun produccion."""
    global _SECCIONES_CACHE
    if _SECCIONES_CACHE is None:
        from app.core.proposal_generator import _REQUIRED_HEADINGS

        _SECCIONES_CACHE = tuple(label for label, _ in _REQUIRED_HEADINGS)
    return _SECCIONES_CACHE


def __getattr__(nombre: str):
    # ``from evals.runner import SECCIONES_REQUERIDAS`` (lo usan los tests)
    # entra por aca: el contrato vive en produccion y no se copia.
    if nombre == "SECCIONES_REQUERIDAS":
        return _secciones_requeridas()
    raise AttributeError(f"module {__name__!r} has no attribute {nombre!r}")

RUTA_CASES = Path(__file__).with_name("cases.yaml")
RUTA_RESULTADOS = Path(__file__).with_name("results")
RAIZ_REPO = Path(__file__).resolve().parent.parent

# Espera base entre llamadas. El free tier de Groq son 30 RPM (2 s por request),
# asi que 2.2 s deja margen. Ajustar con --sleep si el proveedor lo permite.
SLEEP_POR_DEFECTO = 2.2

# Reintentos ante 429. Las fallas por rate limit llegan en rafagas: si se
# pierden sin reintentar, la muestra queda sesgada hacia los casos que tuvieron
# suerte con el timing.
REINTENTOS_POR_DEFECTO = 2

# Fraccion minima de invocaciones exitosas para que la corrida cuente como
# medicion. Con menos, las medias salen de una muestra que no es la planeada.
MIN_OK_RATE_POR_DEFECTO = 0.9

# Un rango de cita mas largo que esto (``[1-999]``) no es una cita plausible:
# se cuentan solo los extremos para no inflar los marcadores.
LARGO_MAX_RANGO_CITA = 20

# Paquetes cuya version entra en la metadata de procedencia.
PAQUETES_PROCEDENCIA = (
    "langchain",
    "langchain-core",
    "langchain-openai",
    "openai",
    "pyyaml",
)


# =============================================================================
# Scorer puro
# =============================================================================

_RE_HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
_RE_FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
_RE_CODIGO_INLINE = re.compile(r"(`+)(?:(?!\1).)+?\1")
# ``[1]``, ``[1, 2]``, ``[1-3]``, ``[1–3]`` y combinaciones (``[1, 3-4]``).
_RE_MARCADOR = re.compile(r"\[(\d+(?:\s*[,\-–]\s*\d+)*)\]")
_RE_BULLET = re.compile(r"^\s*(?:[-*+•]|\d+[.)])\s+\S")


def _normalizar_heading(texto: str) -> str:
    """Compara encabezados como hace produccion: sin acentos, sin mayusculas
    y sin espacios sobrantes.

    Antes NO normalizaba acentos porque el prompt pedia ``Tecnologías`` con
    tilde y eso se media como parte del contrato. Produccion normaliza (su
    ``_normalize_text`` quita acentos), asi que el scorer media como fallida
    toda propuesta valida de produccion (review de #108, lau2413).
    """
    from app.core.proposal_generator import _normalize_text

    return " ".join(_normalize_text(texto).split())


def _clave_de_seccion(texto: str) -> str:
    """Clave normalizada de la seccion obligatoria que matchea este encabezado.

    Usa los patrones y la decoracion tolerada de produccion
    (``_REQUIRED_HEADINGS`` y ``_HEADING_DECOR``), asi que el scorer acepta las
    mismas variantes que el validador de produccion (plural, numeracion,
    negritas, acentos). Si no matchea ninguna seccion obligatoria, devuelve el
    texto normalizado: se cuenta como seccion extra.
    """
    from app.core.proposal_generator import _HEADING_DECOR, _REQUIRED_HEADINGS

    limpio = re.sub("^" + _HEADING_DECOR, "", texto.strip())
    normalizado = _normalizar_heading(limpio)
    for label, patron in _REQUIRED_HEADINGS:
        if re.match(patron, normalizado):
            return _normalizar_heading(label)
    return normalizado


def _sin_codigo(markdown: str) -> list[str]:
    """Lineas del markdown con el codigo borrado, conservando los indices.

    Un ``## Algo`` dentro de un bloque de codigo no es un encabezado, y un
    ``arr[0]`` no es una cita. Las lineas de un bloque cercado (incluidas las
    cercas) quedan vacias y el codigo inline se elimina de la linea.
    """
    salida: list[str] = []
    cerca_abierta: str | None = None
    for linea in markdown.splitlines():
        match = _RE_FENCE.match(linea)
        if cerca_abierta is not None:
            if match and match.group(1)[0] == cerca_abierta[0] and len(
                match.group(1)
            ) >= len(cerca_abierta):
                cerca_abierta = None
            salida.append("")
            continue
        if match:
            cerca_abierta = match.group(1)
            salida.append("")
            continue
        salida.append(_RE_CODIGO_INLINE.sub("", linea))
    return salida


def _headings(lineas: list[str]) -> list[tuple[int, int, str]]:
    """Devuelve ``(indice_linea, nivel, texto)`` de cada encabezado markdown."""
    encontrados: list[tuple[int, int, str]] = []
    for indice, linea in enumerate(lineas):
        match = _RE_HEADING.match(linea)
        if match:
            encontrados.append((indice, len(match.group(1)), match.group(2).strip()))
    return encontrados


def _expandir_marcador(contenido: str) -> list[int]:
    """``"1, 3-4"`` -> ``[1, 3, 4]``. Un rango absurdo cuenta solo sus extremos."""
    numeros: list[int] = []
    for parte in contenido.split(","):
        extremos = [int(n) for n in re.split(r"\s*[\-–]\s*", parte.strip())]
        if len(extremos) == 1:
            numeros.append(extremos[0])
            continue
        desde, hasta = extremos[0], extremos[-1]
        if desde <= hasta and hasta - desde <= LARGO_MAX_RANGO_CITA:
            numeros.extend(range(desde, hasta + 1))
        else:
            numeros.extend([desde, hasta])
    return numeros


def marcadores_cita(markdown: str) -> list[int]:
    """Indices numericos citados en el texto, en orden de aparicion.

    Acepta ``[N]``, listas ``[1, 2]`` y rangos ``[1-3]``. Ignora el codigo
    (``arr[0]`` en un bloque no es una cita) y el texto no numerico: un enlace
    como ``[Componentes](#seccion)`` no se cuenta.
    """
    texto = "\n".join(_sin_codigo(markdown or ""))
    marcadores: list[int] = []
    for contenido in _RE_MARCADOR.findall(texto):
        marcadores.extend(_expandir_marcador(contenido))
    return marcadores


def score_output(
    markdown: str, caso: dict, finish_reason: str | None = None
) -> dict[str, Any]:
    """Puntua una propuesta generada contra el caso del golden set.

    Funcion pura: no hace red, no usa DB, no llama al LLM.

    ``pass_estructural`` exige seis condiciones: el contrato de produccion
    completo (``secciones_ok``: las cinco secciones, el riesgo o costo de la
    justificacion, la tabla de trade-offs citando fuentes ``[n]`` distintas y
    el punto de decision), en orden (``orden_ok``), sin encabezados extra
    (``sin_secciones_extra``), sin texto antes de la primera seccion
    (``sin_preambulo``), con todas las citas dentro de rango
    (``citas_validas``) y sin corte por limite de tokens (``sin_corte``).
    ``cierre_suelto`` es informativo y no entra al pass.

    Las secciones se reconocen en cualquier nivel de encabezado (``#`` a
    ``######``), igual que produccion: un ``### Componentes`` es la seccion
    Componentes, no un encabezado desconocido.
    """
    markdown = markdown or ""
    citas = caso.get("citations") or []
    total_citas = len(citas)
    claves_requeridas = [_normalizar_heading(s) for s in _secciones_requeridas()]
    requeridas = set(claves_requeridas)

    lineas = _sin_codigo(markdown)
    lineas_originales = markdown.splitlines()
    headings = _headings(lineas)

    # Primera aparicion de cada seccion obligatoria, en cualquier nivel. Los
    # patrones son los de produccion, asi que el scorer acepta las mismas
    # variantes. ``primera[clave] = (indice_linea, nivel)``.
    primera: dict[str, tuple[int, int]] = {}
    duplicadas: list[str] = []
    for indice, nivel, texto in headings:
        clave = _clave_de_seccion(texto)
        if clave in requeridas:
            if clave in primera:
                duplicadas.append(texto)
            else:
                primera[clave] = (indice, nivel)

    # El veredicto de "secciones completas" es el de PRODUCCION, con los mismos
    # argumentos que ``generate_stream``: ``source_count`` es el numero de
    # citas, y con fuentes la tabla de trade-offs debe citarlas como ``[n]``
    # distintos. Con 0 esa regla se salteaba y el scorer aprobaba propuestas
    # que produccion rechaza (re-review de #108).
    from app.core.proposal_generator import _missing_sections

    faltantes = _missing_sections(markdown, source_count=total_citas)
    secciones_ok = not faltantes

    # Orden, sobre los encabezados reales (fuera del codigo). El validador de
    # produccion no ignora el codigo: si una seccion solo aparece dentro de un
    # bloque cercado, produccion la da por presente pero aca no tiene posicion,
    # y el orden no se puede afirmar (False, nunca un KeyError).
    orden_ok = False
    if secciones_ok and all(c in primera for c in claves_requeridas):
        orden = [primera[c][0] for c in claves_requeridas]
        orden_ok = orden == sorted(orden)

    # Extra: cualquier `#` o `##` que no sea una seccion obligatoria. Los
    # subtitulos (`###` o mas) dentro de una seccion se permiten. Repetir una
    # obligatoria no cuenta como extra; se reporta en `secciones_duplicadas`.
    extras = [
        f"# {t}" if nivel == 1 else t
        for _, nivel, t in headings
        if nivel <= 2 and _clave_de_seccion(t) not in requeridas
    ]
    sin_secciones_extra = not extras

    # Preambulo: cualquier contenido (incluido un H1 o un bloque de codigo)
    # antes del primer encabezado de cuerpo (una seccion obligatoria en
    # cualquier nivel, o cualquier `##` o menor). El prompt pide responder
    # "exactamente" con las cinco secciones.
    inicio_cuerpo = next(
        (
            i
            for i, nivel, t in headings
            if nivel >= 2 or _clave_de_seccion(t) in requeridas
        ),
        len(lineas_originales),
    )
    sin_preambulo = not any(l.strip() for l in lineas_originales[:inicio_cuerpo])

    # Cierre suelto: la ultima linea con contenido no es un bullet ni la
    # continuacion indentada de uno (p.ej. "Espero que te sirva"). Es
    # informativo: un parrafo final legitimo dentro de Trade-offs y decision
    # tambien lo dispara, asi que no se usa para el pass.
    ultima = next((l for l in reversed(lineas) if l.strip()), "")
    cierre_suelto = bool(
        primera
        and ultima.strip()
        and not _RE_BULLET.match(ultima)
        and not ultima.startswith((" ", "\t"))
        and not _RE_HEADING.match(ultima)
    )

    # Citas: todos los marcadores deben caer dentro del rango provisto. Con
    # citations vacias, cualquier marcador es invalido (fallo esperado del
    # modelo, no del scorer).
    marcadores = marcadores_cita(markdown)
    fuera_de_rango = [n for n in marcadores if n < 1 or n > total_citas]
    citas_validas = not fuera_de_rango

    # Corte por limite de tokens: produccion descarta la propuesta con
    # ``finish_reason == "length"`` aunque tenga todas las secciones.
    sin_corte = finish_reason != "length"

    # Bullets por seccion: lineas con `-`, `*`, `+`, `•` o `1.` dentro del
    # tramo que va desde el encabezado de la seccion hasta el siguiente
    # encabezado de su mismo nivel o superior (el criterio de produccion para
    # delimitar la seccion de trade-offs). Una seccion sin encabezado real
    # cuenta 0.
    bullets_por_seccion: dict[str, int] = {}
    for seccion, clave in zip(_secciones_requeridas(), claves_requeridas):
        if clave not in primera:
            bullets_por_seccion[seccion] = 0
            continue
        inicio, nivel_seccion = primera[clave]
        fin = next(
            (i for i, nivel, _ in headings if i > inicio and nivel <= nivel_seccion),
            len(lineas),
        )
        bullets_por_seccion[seccion] = sum(
            1 for l in lineas[inicio + 1 : fin] if _RE_BULLET.match(l)
        )

    pass_estructural = bool(
        secciones_ok
        and orden_ok
        and sin_secciones_extra
        and sin_preambulo
        and citas_validas
        and sin_corte
    )

    return {
        "vacio": not markdown.strip(),
        "secciones_ok": secciones_ok,
        "secciones_faltantes": faltantes,
        "orden_ok": orden_ok,
        "sin_secciones_extra": sin_secciones_extra,
        "sin_preambulo": sin_preambulo,
        "citas_validas": citas_validas,
        "sin_corte": sin_corte,
        "pass_estructural": pass_estructural,
        "cierre_suelto": cierre_suelto,
        "bullets_por_seccion": bullets_por_seccion,
        "largo": len(markdown),
        "marcadores": marcadores,
        "marcadores_fuera_de_rango": fuera_de_rango,
        "secciones_duplicadas": duplicadas,
        "secciones_extra": extras,
    }


# =============================================================================
# Carga y validacion de casos
# =============================================================================


def cargar_casos(ruta: Path = RUTA_CASES) -> list[dict]:
    """Lee ``cases.yaml`` y valida el schema minimo de cada caso.

    ``citations`` ausente o ``null`` se toma como lista vacia. ``feedback`` y
    ``prior_content`` son opcionales y cubren el camino de iteracion.
    """
    with ruta.open(encoding="utf-8") as fh:
        datos = yaml.safe_load(fh)

    if not isinstance(datos, dict) or not isinstance(datos.get("casos"), list):
        raise ValueError(f"{ruta} debe tener una clave 'casos' con una lista")

    casos = datos["casos"]
    if not casos:
        raise ValueError(f"{ruta} no define ningun caso")

    vistos: set[str] = set()
    for posicion, caso in enumerate(casos):
        where = f"caso #{posicion}"
        if not isinstance(caso, dict):
            raise ValueError(f"{where}: se esperaba un mapping")
        for campo in ("id", "nombre", "project_name", "descripcion"):
            valor = caso.get(campo)
            if not isinstance(valor, str) or not valor.strip():
                raise ValueError(f"{where}: campo '{campo}' ausente o vacio")
            where = f"caso '{caso['id']}'"
        if caso["id"] in vistos:
            raise ValueError(f"{where}: id duplicado")
        vistos.add(caso["id"])

        for campo in ("feedback", "prior_content"):
            valor = caso.get(campo)
            if valor is not None and (not isinstance(valor, str) or not valor.strip()):
                raise ValueError(f"{where}: '{campo}' debe ser texto no vacio u omitirse")
            caso[campo] = valor

        citations = caso.get("citations")
        if citations is None:
            citations = []
        if not isinstance(citations, list):
            raise ValueError(f"{where}: 'citations' debe ser una lista")
        for posicion_cita, cita in enumerate(citations, start=1):
            if not isinstance(cita, dict):
                raise ValueError(f"{where}: cita #{posicion_cita} no es un mapping")
            for campo in ("pattern_name", "snippet"):
                if not isinstance(cita.get(campo), str) or not cita[campo].strip():
                    raise ValueError(
                        f"{where}: la cita #{posicion_cita} no tiene '{campo}'"
                    )
        caso["citations"] = citations

    return casos


def armar_prompt(caso: dict) -> str:
    """Prompt de produccion para el caso. Unico punto que llama a ``_build_prompt``."""
    from app.core.proposal_generator import _build_prompt

    return _build_prompt(
        caso["citations"],
        caso.get("prior_content"),
        caso.get("feedback"),
        caso["project_name"],
        # La descripcion entra al prompt desde que produccion la acepta
        # (#112). El harness tiene que medir EL MISMO prompt: sin esto,
        # mediria un prompt que la app nunca arma.
        description=caso.get("descripcion"),
        requirements_text=caso.get("requirements_text"),
        documents_text=caso.get("documents_text"),
    )


def dry_run(casos: list[dict]) -> int:
    """Valida el corpus y arma el prompt de cada caso. Sin API key ni red."""
    print(f"Casos cargados: {len(casos)}\n")
    print(f"{'id':<12} {'proyecto':<26} {'citas':>5}  {'iter':>4}  nombre")
    print("-" * 100)
    for caso in casos:
        iteracion = "si" if caso.get("feedback") or caso.get("prior_content") else "-"
        print(
            f"{caso['id']:<12} {caso['project_name']:<26} "
            f"{len(caso['citations']):>5}  {iteracion:>4}  {caso['nombre']}"
        )

    sin_citas = [c["id"] for c in casos if not c["citations"]]
    print()
    print(f"Casos con citations: [] -> {len(sin_citas)} ({', '.join(sin_citas) or '-'})")
    print(
        f"Secciones obligatorias: {', '.join(_secciones_requeridas())} "
        f"(contrato de produccion: cualquier nivel de encabezado, sin "
        f"distinguir acentos ni mayusculas)"
    )

    # Se arma el prompt real de CADA caso: si alguno no se puede construir, el
    # runner nunca podra medirlo, asi que el dry-run falla con exit 1 en vez de
    # avisar y seguir (el falso verde del bug B1).
    errores: list[str] = []
    prompts: dict[str, str] = {}
    for caso in casos:
        try:
            prompts[caso["id"]] = armar_prompt(caso)
        except Exception as exc:  # noqa: BLE001 -- queremos reportar y abortar
            errores.append(f"{caso['id']}: {type(exc).__name__}: {exc}")
    if errores:
        print("\n[ERROR] No se pudo construir el prompt con _build_prompt:", file=sys.stderr)
        for error in errores:
            print(f"  - {error}", file=sys.stderr)
        return 1

    primero = casos[0]["id"]
    print(f"\nPrompts armados: {len(prompts)}. Muestra de '{primero}' "
          f"({len(prompts[primero])} caracteres):")
    print("-" * 60)
    print(prompts[primero])

    print("\n[OK] Corpus valido. No se realizo ninguna llamada de red.")
    return 0


# =============================================================================
# Metricas de variabilidad
# =============================================================================


def _jaccard(a: set[int], b: set[int]) -> float:
    """Jaccard de dos conjuntos de marcadores. Dos vacios = 1.0 (coinciden)."""
    union = a | b
    if not union:
        return 1.0
    return len(a & b) / len(union)


def _normalizar_espacios(markdown: str) -> str:
    """Quita espacios al final de linea, lineas vacias repetidas y bordes."""
    lineas = [l.rstrip() for l in markdown.strip().splitlines()]
    compactas: list[str] = []
    for linea in lineas:
        if linea or (compactas and compactas[-1]):
            compactas.append(linea)
    return "\n".join(compactas)


def calcular_variabilidad(
    ejecuciones: list[dict], caso_id: str, modelo: str
) -> dict[str, Any]:
    """Agrega los repeats de un mismo (caso, modelo) en metricas de variabilidad.

    Solo entra lo que salio bien; los fallos se excluyen del calculo. Las
    metricas que necesitan pares (o una dispersion) quedan en ``None`` con
    menos de dos repeats exitosos: un 0.0 ahi seria un "estable" inventado.
    """
    propias = [e for e in ejecuciones if e["caso_id"] == caso_id and e["modelo"] == modelo]
    exitosas = [e for e in propias if e.get("ok")]
    n = len(exitosas)
    resumen: dict[str, Any] = {
        "caso_id": caso_id,
        "modelo": modelo,
        "repeats_ok": n,
        "repeats_fallidos": len(propias) - n,
        "pares": n * (n - 1) // 2,
        "tasa_pass_estructural": None,
        "largo_medio": None,
        "desvio_largo": None,
        "salidas_distintas": None,
        "tasa_exacta": None,
        "tasa_exacta_normalizada": None,
        "similitud_media": None,
        "acuerdo_estructural": None,
        "solapamiento_citas": None,
    }
    if n == 0:
        return resumen

    largos = [e["score"]["largo"] for e in exitosas]
    resumen["largo_medio"] = statistics.fmean(largos)
    resumen["salidas_distintas"] = len({e["markdown"] for e in exitosas})
    resumen["tasa_pass_estructural"] = statistics.fmean(
        1.0 if e["score"]["pass_estructural"] else 0.0 for e in exitosas
    )

    if n < 2:
        return resumen

    resumen["desvio_largo"] = statistics.pstdev(largos)
    pares = list(itertools.combinations(exitosas, 2))
    resumen["tasa_exacta"] = statistics.fmean(
        1.0 if a["markdown"] == b["markdown"] else 0.0 for a, b in pares
    )
    resumen["tasa_exacta_normalizada"] = statistics.fmean(
        1.0
        if _normalizar_espacios(a["markdown"]) == _normalizar_espacios(b["markdown"])
        else 0.0
        for a, b in pares
    )
    resumen["similitud_media"] = statistics.fmean(
        difflib.SequenceMatcher(None, a["markdown"], b["markdown"], autojunk=False).ratio()
        for a, b in pares
    )
    resumen["acuerdo_estructural"] = statistics.fmean(
        1.0
        if a["score"]["pass_estructural"] == b["score"]["pass_estructural"]
        else 0.0
        for a, b in pares
    )
    resumen["solapamiento_citas"] = statistics.fmean(
        _jaccard(set(a["score"]["marcadores"]), set(b["score"]["marcadores"]))
        for a, b in pares
    )
    return resumen


def resumir_por_modelo(variabilidad: list[dict], ejecuciones: list[dict]) -> dict:
    """Medias de cada metrica por modelo, solo sobre los casos medibles.

    Un caso es medible con dos o mas repeats exitosos. Los casos sin datos no
    entran a ninguna media (antes aportaban un ``desvio_largo`` de 0.0 que
    tiraba el resumen hacia "estable").
    """
    modelos = sorted({v["modelo"] for v in variabilidad})
    resumen: dict[str, Any] = {}
    for modelo in modelos:
        filas = [v for v in variabilidad if v["modelo"] == modelo]
        medibles = [f for f in filas if f["repeats_ok"] >= 2]
        propias = [e for e in ejecuciones if e["modelo"] == modelo]
        exitosas = [e for e in propias if e.get("ok")]

        def _media(clave: str) -> float | None:
            valores = [f[clave] for f in medibles if f.get(clave) is not None]
            return statistics.fmean(valores) if valores else None

        resumen[modelo] = {
            "casos": len(filas),
            "casos_medibles": len(medibles),
            # `acuerdo_estructural` alto puede ser "pasa siempre" o "falla
            # siempre": estos dos conteos dicen cual de las dos.
            "casos_pass_siempre": sum(
                1 for f in medibles if f["tasa_pass_estructural"] == 1.0
            ),
            "casos_falla_siempre": sum(
                1 for f in medibles if f["tasa_pass_estructural"] == 0.0
            ),
            "ejecuciones": len(propias),
            "ejecuciones_ok": len(exitosas),
            "ejecuciones_fallidas": len(propias) - len(exitosas),
            "tasa_pass_estructural": (
                statistics.fmean(
                    1.0 if e["score"]["pass_estructural"] else 0.0 for e in exitosas
                )
                if exitosas
                else None
            ),
            "tasa_exacta": _media("tasa_exacta"),
            "tasa_exacta_normalizada": _media("tasa_exacta_normalizada"),
            "similitud_media": _media("similitud_media"),
            "acuerdo_estructural": _media("acuerdo_estructural"),
            "solapamiento_citas": _media("solapamiento_citas"),
            "desvio_largo": _media("desvio_largo"),
        }
    return resumen


# =============================================================================
# Procedencia
# =============================================================================


def _sha256(texto: str | bytes) -> str:
    datos = texto.encode("utf-8") if isinstance(texto, str) else texto
    return hashlib.sha256(datos).hexdigest()


def _git(*args: str) -> str | None:
    try:
        salida = subprocess.run(
            ["git", *args],
            cwd=RAIZ_REPO,
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return salida.stdout.strip()


def _version(paquete: str) -> str | None:
    try:
        return importlib.metadata.version(paquete)
    except importlib.metadata.PackageNotFoundError:
        return None


def temperatura_efectiva(modelo: str, temperature: float) -> float | None:
    """La temperatura que de verdad viaja al proveedor; ``None`` si se omite.

    Para la serie ``o*`` el kwarg no se manda y el proveedor aplica la suya
    (1). Registrar la solicitada en ese caso seria mentir en la metadata.
    """
    from app.core.llm_loader import _acepta_temperature

    return temperature if _acepta_temperature(modelo) else None


def procedencia(prompts: dict[str, str]) -> dict[str, Any]:
    """Lo necesario para auditar o reproducir un baseline."""
    from app.core.proposal_generator import _build_prompt

    estado = _git("status", "--porcelain")
    return {
        "git_commit": _git("rev-parse", "HEAD"),
        "git_sucio": bool(estado) if estado is not None else None,
        "cases_yaml_sha256": _sha256(RUTA_CASES.read_bytes()),
        "build_prompt_fuente_sha256": _sha256(inspect.getsource(_build_prompt)),
        "prompts_sha256": {cid: _sha256(p) for cid, p in prompts.items()},
        "python": platform.python_version(),
        "plataforma": platform.platform(),
        "paquetes": {p: _version(p) for p in PAQUETES_PROCEDENCIA},
        "argv": sys.argv[1:],
    }


# =============================================================================
# Runner de ejecucion
# =============================================================================


def resolver_temperatura(solicitada: float | None) -> tuple[float, str]:
    """``(temperatura, origen)`` con la misma regla que produccion.

    Sin ``--temperature`` se usa ``llm_temperature()`` de
    ``app/core/llm_loader.py``: ``LLM_TEMPERATURE`` si es valida, si no
    ``DEFAULT_LLM_TEMPERATURE``. El origen va a la metadata para que un
    baseline diga de donde salio el valor.
    """
    if solicitada is not None:
        return solicitada, "--temperature"

    from app.core.llm_loader import LLM_TEMPERATURE_ENV, llm_temperature

    valor = llm_temperature()
    raw = os.getenv(LLM_TEMPERATURE_ENV, "").strip()
    try:
        desde_env = bool(raw) and float(raw) == valor
    except ValueError:
        desde_env = False
    return valor, LLM_TEMPERATURE_ENV if desde_env else "DEFAULT_LLM_TEMPERATURE"


def construir_modelo(modelo: str, base_url: str, api_key: str, temperature: float):
    """Construye el modelo LangChain igual que lo hace la app en produccion.

    La temperatura llega resuelta por ``resolver_temperatura`` (por defecto, la
    misma que manda produccion); ``--temperature`` permite medir el corpus con
    otros valores. La regla de si el modelo acepta ``temperature`` (la serie
    ``o*``, ``gpt-5`` no-chat y ``LLM_MODELS_WITHOUT_TEMPERATURE``) se delega a
    produccion (``_acepta_temperature``) para no duplicarla.
    """
    from langchain.chat_models import init_chat_model

    from app.core.llm_loader import _acepta_temperature

    kwargs: dict = {
        "model": modelo,
        "model_provider": "openai",
        "base_url": base_url,
        "api_key": api_key,
    }
    if _acepta_temperature(modelo):
        kwargs["temperature"] = temperature

    return init_chat_model(**kwargs)


def resolver_proveedor(env: dict[str, str]) -> tuple[str, str, str]:
    """``(base_url, api_key, modelo_default)`` con los mismos defaults que la app.

    Sin ``LLM_BASE_URL`` se usa el endpoint default de la app (Groq), y ahi la
    credencial puede venir de ``GROQ_API_KEY``, la misma variable que lee
    produccion. Contra otro endpoint hace falta ``LLM_API_KEY`` explicita: la
    clave de Groq no se manda a un tercero.
    """
    from app.core.llm_loader import DEFAULT_LLM_BASE_URL, DEFAULT_LLM_MODEL

    base_url = env.get("LLM_BASE_URL", "").strip() or DEFAULT_LLM_BASE_URL
    api_key = env.get("LLM_API_KEY", "").strip()
    if not api_key and base_url.rstrip("/") == DEFAULT_LLM_BASE_URL.rstrip("/"):
        api_key = env.get("GROQ_API_KEY", "").strip()
    modelo = env.get("LLM_MODEL", "").strip() or DEFAULT_LLM_MODEL
    return base_url, api_key, modelo


def _es_rate_limit(exc: Exception) -> bool:
    """Detecta 429 sin depender del SDK del proveedor."""
    if getattr(exc, "status_code", None) == 429:
        return True
    texto = str(exc).lower()
    # "429" como palabra: un numero mayor (p.ej. "4290") no es un rate limit.
    return (
        re.search(r"\b429\b", texto) is not None
        or "rate limit" in texto
        or "too many requests" in texto
    )


def _contenido(respuesta: Any) -> str:
    """Normaliza la respuesta (o un chunk) del chat a texto plano."""
    contenido = getattr(respuesta, "content", respuesta)
    if isinstance(contenido, str):
        return contenido
    if isinstance(contenido, list):
        partes = []
        for bloque in contenido:
            if isinstance(bloque, str):
                partes.append(bloque)
            elif isinstance(bloque, dict) and isinstance(bloque.get("text"), str):
                partes.append(bloque["text"])
        return "".join(partes)
    if contenido is None:
        return ""
    return str(contenido)


def _invocar(chat: Any, prompt: str, stream_usage: bool) -> dict[str, Any]:
    """Una llamada al modelo por streaming, como ``generate_stream`` en produccion.

    Concatena el contenido de los chunks igual que produccion y suma los
    chunks para recuperar ``finish_reason`` y ``usage`` (que llegan en el
    ultimo). ``finish_reason == "length"`` es la firma de un modelo de
    razonamiento que se quedo sin presupuesto de tokens.
    """
    kwargs = {"stream_usage": True} if stream_usage else {}
    partes: list[str] = []
    agregado: Any = None
    for chunk in chat.stream(prompt, **kwargs):
        texto = _contenido(chunk)
        if texto:
            partes.append(texto)
        try:
            agregado = chunk if agregado is None else agregado + chunk
        except TypeError:
            agregado = chunk

    metadata = getattr(agregado, "response_metadata", None)
    usage = getattr(agregado, "usage_metadata", None)
    return {
        "markdown": "".join(partes),
        "finish_reason": metadata.get("finish_reason") if isinstance(metadata, dict) else None,
        "usage": dict(usage) if isinstance(usage, dict) else None,
    }


def _ejecutar_una(
    chat: Any, prompt: str, caso: dict, args: argparse.Namespace
) -> dict[str, Any]:
    """Invoca con reintentos ante 429 y puntua. Nunca lanza."""
    intentos = 0
    while True:
        intentos += 1
        started = time.perf_counter()
        try:
            respuesta = _invocar(chat, prompt, args.stream_usage)
        except Exception as exc:  # noqa: BLE001 -- seguir ante 429/500/timeout
            mensaje = f"{type(exc).__name__}: {exc}"
            if _es_rate_limit(exc) and intentos <= args.retries:
                espera = max(args.sleep, 1.0) * 2**intentos
                print(f"    rate limit (intento {intentos}): esperando {espera:.1f}s")
                time.sleep(espera)
                continue
            return {"ok": False, "error": mensaje, "intentos": intentos}

        ms = int((time.perf_counter() - started) * 1000)
        markdown = respuesta["markdown"]
        resultado: dict[str, Any] = {
            "intentos": intentos,
            "latencia_ms": ms,
            "markdown": markdown,
            "finish_reason": respuesta["finish_reason"],
            "usage": respuesta["usage"],
        }
        # Una salida vacia no es una propuesta: si contara como exito, tres
        # vacias darian exacta = acuerdo = citas = 1.0, "reproducibilidad
        # perfecta" de nada. Produccion la trata igual ("LLM returned no
        # content").
        if not markdown.strip():
            resultado.update(
                ok=False,
                error=f"contenido vacio (finish_reason={respuesta['finish_reason']})",
            )
            return resultado
        # Un bug del scorer no puede tirar la corrida: la excepcion subiria
        # hasta `main` sin escribir el JSON y se perderia todo lo medido (con
        # tokens reales). La salida queda guardada para re-puntuarla despues.
        try:
            score = score_output(markdown, caso, respuesta["finish_reason"])
        except Exception as exc:  # noqa: BLE001 -- nunca lanza
            resultado.update(
                ok=False, error=f"error del scorer: {type(exc).__name__}: {exc}"
            )
            return resultado
        resultado.update(ok=True, score=score)
        return resultado


def _evaluar_gate(
    ejecuciones: list[dict],
    planeadas: int,
    errores_construccion: list[dict],
    variabilidad: list[dict],
    min_ok_rate: float,
) -> list[str]:
    """Motivos por los que la corrida no vale como medicion. Vacio = paso."""
    motivos: list[str] = []
    exitosas = sum(1 for e in ejecuciones if e.get("ok"))
    tasa_ok = exitosas / planeadas if planeadas else 0.0
    if errores_construccion:
        nombres = ", ".join(e["modelo"] for e in errores_construccion)
        motivos.append(f"no se pudo construir: {nombres}")
    if exitosas == 0:
        motivos.append("ninguna invocacion fue exitosa")
    elif tasa_ok < min_ok_rate:
        motivos.append(
            f"tasa de exito {tasa_ok:.1%} ({exitosas}/{planeadas}) "
            f"por debajo de --min-ok-rate {min_ok_rate:.0%}"
        )
    if not any(v["repeats_ok"] >= 2 for v in variabilidad):
        motivos.append("ningun par (caso, modelo) tuvo 2 repeats exitosos: no hay metricas")
    return motivos


def ejecutar_corrida(args: argparse.Namespace) -> int:
    """Corre el golden set completo. Un caso que falla no aborta la corrida."""
    casos = cargar_casos()
    por_id = {c["id"]: c for c in casos}
    if args.case:
        desconocidos = [cid for cid in args.case if cid not in por_id]
        if desconocidos:
            print(
                f"--case desconocido: {', '.join(desconocidos)}\n"
                f"Casos validos: {', '.join(por_id)}",
                file=sys.stderr,
            )
            return 2
        casos_seleccionados = [por_id[cid] for cid in dict.fromkeys(args.case)]
    else:
        casos_seleccionados = casos

    base_url, api_key, modelo_default = resolver_proveedor(dict(os.environ))
    if not api_key:
        print(
            "Falta la API key: defini LLM_API_KEY (o GROQ_API_KEY si usas el "
            "endpoint default de Groq).\n"
            "Usa --dry-run para validar el corpus sin red.",
            file=sys.stderr,
        )
        return 2

    modelos = args.models.split(",") if args.models else [modelo_default]
    modelos = list(dict.fromkeys(m.strip() for m in modelos if m.strip()))
    if not modelos:
        print("--models no contiene ningun modelo", file=sys.stderr)
        return 2

    # Los prompts se arman una vez: son deterministas y su hash va a la
    # metadata. Si uno no se puede armar, la corrida no tiene sentido.
    try:
        prompts = {c["id"]: armar_prompt(c) for c in casos_seleccionados}
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] No se pudo construir el prompt: {exc}", file=sys.stderr)
        return 1

    temperature, origen_temperatura = resolver_temperatura(args.temperature)

    planeadas = len(casos_seleccionados) * len(modelos) * args.repeats
    print(f"Proveedor  : {base_url}")
    print(f"Modelos    : {', '.join(modelos)}")
    print(f"Casos      : {len(casos_seleccionados)}")
    print(f"Repeats    : {args.repeats} (intercalados: repeat > caso > modelo)")
    print(f"Temperatura: {temperature} (origen: {origen_temperatura})")
    print(f"Espera     : {args.sleep}s entre llamadas, {args.retries} reintentos ante 429")
    print(f"Total de invocaciones: {planeadas}\n")

    chats: dict[str, Any] = {}
    errores_construccion: list[dict] = []
    for modelo in modelos:
        if "groq.com" in base_url and modelo.startswith("gpt-oss"):
            print(f"[AVISO] Groq publica '{modelo}' como 'openai/{modelo}'.")
        try:
            chats[modelo] = construir_modelo(modelo, base_url, api_key, temperature)
        except Exception as exc:  # noqa: BLE001 -- un modelo malo no corta todo
            mensaje = f"{type(exc).__name__}: {exc}"
            print(f"[ERROR] No se pudo construir el modelo '{modelo}': {mensaje}")
            errores_construccion.append({"modelo": modelo, "error": mensaje})

    # Orden intercalado: los repeats de un mismo caso quedan separados por el
    # resto del corpus, para no medirlos todos bajo las mismas condiciones de
    # serving (mismo lote, misma maquina, mismos segundos).
    plan = [
        (repeat, caso, modelo)
        for repeat in range(1, args.repeats + 1)
        for caso in casos_seleccionados
        for modelo in modelos
        if modelo in chats
    ]
    ejecuciones: list[dict] = []
    for orden, (repeat, caso, modelo) in enumerate(plan, start=1):
        marca = f"[{caso['id']} | {modelo} | repeat {repeat}/{args.repeats}]"
        inicio = datetime.now(timezone.utc).isoformat(timespec="seconds")
        resultado = _ejecutar_una(chats[modelo], prompts[caso["id"]], caso, args)
        ejecuciones.append(
            {
                "caso_id": caso["id"],
                "modelo": modelo,
                "repeat": repeat,
                "orden": orden,
                "inicio_utc": inicio,
                **resultado,
            }
        )
        if resultado["ok"]:
            score = resultado["score"]
            estado = "OK " if score["pass_estructural"] else "KO "
            print(
                f"{marca} {estado} {score['largo']:>5} chars  "
                f"{resultado['latencia_ms']:>6} ms  "
                f"secciones={score['secciones_ok']} orden={score['orden_ok']} "
                f"preambulo={not score['sin_preambulo']} "
                f"citas={score['citas_validas']} extra={score['secciones_extra']}"
            )
        else:
            print(f"{marca} FALLO: {resultado['error'][:160]}")

        if args.sleep > 0 and orden < len(plan):
            time.sleep(args.sleep)

    variabilidad = [
        calcular_variabilidad(ejecuciones, caso["id"], modelo)
        for modelo in chats
        for caso in casos_seleccionados
    ]
    resumen = resumir_por_modelo(variabilidad, ejecuciones)
    for error in errores_construccion:
        resumen[error["modelo"]] = {"error_construccion": error["error"]}
    motivos = _evaluar_gate(
        ejecuciones, planeadas, errores_construccion, variabilidad, args.min_ok_rate
    )

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    salida = Path(args.output_dir)
    salida.mkdir(parents=True, exist_ok=True)
    ruta_json = salida / f"{timestamp}.json"
    ruta_json.write_text(
        json.dumps(
            {
                "metadata": {
                    "timestamp": timestamp,
                    "base_url": base_url,
                    "modelos": modelos,
                    "casos": [c["id"] for c in casos_seleccionados],
                    "repeats": args.repeats,
                    "orden": "repeat > caso > modelo",
                    "temperature_solicitada": temperature,
                    "temperature_origen": origen_temperatura,
                    "temperature_efectiva": {
                        m: temperatura_efectiva(m, temperature) for m in modelos
                    },
                    "sleep_s": args.sleep,
                    "reintentos_429": args.retries,
                    "min_ok_rate": args.min_ok_rate,
                    "stream_usage": args.stream_usage,
                    "secciones_requeridas": list(_secciones_requeridas()),
                    "procedencia": procedencia(prompts),
                },
                "gate": {"paso": not motivos, "motivos": motivos},
                "errores_construccion": errores_construccion,
                "ejecuciones": ejecuciones,
                "variabilidad": variabilidad,
                "resumen_por_modelo": resumen,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    _imprimir_resumen(resumen, variabilidad, ejecuciones, ruta_json)

    if motivos:
        print("\n[ERROR] La corrida no vale como medicion:", file=sys.stderr)
        for motivo in motivos:
            print(f"  - {motivo}", file=sys.stderr)
        return 1
    return 0


def _fmt(valor: float | None, decimales: int = 3) -> str:
    if valor is None:
        return "n/d"
    return f"{valor:.{decimales}f}"


def _filtrar_peores(variabilidad: list[dict]) -> dict:
    """Particiona ``variabilidad`` segun cuanto se pudo medir cada par.

    Returns:
        ``{"peor": [...], "insuficientes": [...], "all_failed": [...]}``,
        disjuntas. ``peor``: tasa_exacta en [0.0, 1.0). ``insuficientes``:
        exactamente un repeat exitoso (no hay pares). ``all_failed``: ningun
        repeat exitoso. Los pares con tasa_exacta == 1.0 no aparecen.
    """
    peor = [
        v for v in variabilidad
        if v.get("tasa_exacta") is not None and v["tasa_exacta"] < 1.0
    ]
    sin_pares = [v for v in variabilidad if v.get("tasa_exacta") is None]
    return {
        "peor": peor,
        "insuficientes": [v for v in sin_pares if v.get("repeats_ok", 0) > 0],
        "all_failed": [v for v in sin_pares if v.get("repeats_ok", 0) == 0],
    }


def _imprimir_resumen(
    resumen: dict,
    variabilidad: list[dict],
    ejecuciones: list[dict],
    ruta_json: Path,
) -> None:
    print("\n" + "=" * 104)
    print("RESUMEN POR MODELO")
    print("=" * 104)
    print(
        f"{'modelo':<28} {'ok':>7} {'medib':>5} {'struct_ok':>9} {'exacta':>7} "
        f"{'exac_n':>7} {'simil':>6} {'acuerdo':>7} {'citas':>6} {'desv_lg':>8}"
    )
    print("-" * 104)
    for modelo, stats in resumen.items():
        if "error_construccion" in stats:
            print(f"{modelo:<28} NO SE PUDO CONSTRUIR: {stats['error_construccion'][:60]}")
            continue
        ok = f"{stats['ejecuciones_ok']}/{stats['ejecuciones']}"
        print(
            f"{modelo:<28} {ok:>7} {stats['casos_medibles']:>5} "
            f"{_fmt(stats['tasa_pass_estructural']):>9} "
            f"{_fmt(stats['tasa_exacta']):>7} {_fmt(stats['tasa_exacta_normalizada']):>7} "
            f"{_fmt(stats['similitud_media'], 2):>6} "
            f"{_fmt(stats['acuerdo_estructural']):>7} "
            f"{_fmt(stats['solapamiento_citas'], 2):>6} "
            f"{_fmt(stats['desvio_largo'], 1):>8}"
        )
        if stats["casos_medibles"]:
            print(
                f"{'':<28} acuerdo: {stats['casos_pass_siempre']} casos pasan siempre, "
                f"{stats['casos_falla_siempre']} fallan siempre"
            )
    print()
    print("ok         = invocaciones exitosas / planeadas (vacias y errores cuentan como fallo)")
    print("medib      = casos con 2 o mas repeats exitosos; las medias salen solo de estos")
    print("struct_ok  = tasa de salidas que pasan el chequeo estructural completo")
    print("exacta     = fraccion de pares de repeats identicos byte a byte")
    print("exac_n     = idem, ignorando espacios al final de linea y lineas vacias de mas")
    print("simil      = similitud media entre pares (difflib, 0 a 1)")
    print("acuerdo    = fraccion de pares con el mismo pass_estructural (ver 'pasan/fallan siempre')")
    print("citas      = Jaccard medio de los marcadores [N] entre pares")
    print("desv_lg    = desviacion estandar del largo, en caracteres")
    print("n/d        = no calculable (menos de 2 repeats exitosos)")

    fallidos = [e for e in ejecuciones if not e.get("ok")]
    if fallidos:
        print(f"\nEjecuciones fallidas: {len(fallidos)}")
        for e in fallidos[:10]:
            print(f"  - {e['caso_id']} / {e['modelo']} / repeat {e['repeat']}: "
                  f"{e.get('error', '')[:110]}")

    grupos = _filtrar_peores(variabilidad)
    if grupos["peor"]:
        print(f"\nPares (caso, modelo) con al menos un repeat distinto: {len(grupos['peor'])}")
        for v in grupos["peor"]:
            print(
                f"  - {v['caso_id']:<13} {v['modelo']:<24} "
                f"exacta={_fmt(v['tasa_exacta'])} "
                f"distintas={v['salidas_distintas']}/{v['repeats_ok']} "
                f"acuerdo={_fmt(v['acuerdo_estructural'])} "
                f"desv_lg={_fmt(v['desvio_largo'], 1)}"
            )
    for clave, titulo in (
        ("insuficientes", "Pares con un solo repeat exitoso (sin pares que comparar)"),
        ("all_failed", "Pares con todos los repeats fallidos"),
    ):
        if grupos[clave]:
            print(f"\n{titulo}: {len(grupos[clave])}")
            for v in grupos[clave]:
                print(
                    f"  - {v['caso_id']:<13} {v['modelo']:<24} "
                    f"repeats_ok={v['repeats_ok']} "
                    f"repeats_fallidos={v['repeats_fallidos']}"
                )

    print(f"\nDetalle completo: {ruta_json}")


# =============================================================================
# CLI
# =============================================================================


def _fraccion(valor: str) -> float:
    numero = float(valor)
    if not 0.0 <= numero <= 1.0:
        raise argparse.ArgumentTypeError("debe estar entre 0 y 1")
    return numero


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m evals.runner",
        description="Mide la variabilidad de las propuestas de arquitectura.",
    )
    parser.add_argument(
        "--models",
        help=(
            "Modelos a comparar, separados por coma, con el id exacto del "
            "proveedor (en Groq: openai/gpt-oss-120b). Si se omite usa "
            "LLM_MODEL o el modelo default de la app."
        ),
    )
    parser.add_argument(
        "--repeats",
        type=int,
        default=3,
        help="Repeticiones del mismo caso; minimo 2 para tener pares (default: 3).",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=None,
        help=(
            "Temperatura de muestreo. Si se omite usa la de produccion "
            "(llm_temperature() de app/core/llm_loader.py: LLM_TEMPERATURE si "
            "es valida, si no DEFAULT_LLM_TEMPERATURE). A los modelos que no "
            "la admiten (serie o*, gpt-5 no-chat) no se les manda."
        ),
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=SLEEP_POR_DEFECTO,
        help=f"Segundos entre llamadas (default: {SLEEP_POR_DEFECTO}).",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=REINTENTOS_POR_DEFECTO,
        help=f"Reintentos ante 429, con backoff exponencial (default: {REINTENTOS_POR_DEFECTO}).",
    )
    parser.add_argument(
        "--min-ok-rate",
        type=_fraccion,
        default=MIN_OK_RATE_POR_DEFECTO,
        help=(
            "Fraccion minima de invocaciones exitosas para salir con 0 "
            f"(default: {MIN_OK_RATE_POR_DEFECTO})."
        ),
    )
    parser.add_argument(
        "--no-stream-usage",
        dest="stream_usage",
        action="store_false",
        help="No pedir el uso de tokens en el stream (para proveedores que no lo soportan).",
    )
    parser.add_argument(
        "--case",
        action="append",
        metavar="ID",
        help="Ejecutar solo estos casos. Repetible.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(RUTA_RESULTADOS),
        help="Directorio para el JSON de resultados (default: evals/results/).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Valida el corpus y arma los prompts. No llama a la API.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    # En Windows la consola suele venir en cp1252/cp437 y las tildes del corpus
    # se pierden o revientan la impresion. Forzamos UTF-8 en stdout.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass
    if args.dry_run:
        return dry_run(cargar_casos())
    if args.repeats < 2:
        print("--repeats debe ser >= 2: con 1 no hay pares para medir variabilidad",
              file=sys.stderr)
        return 2
    if args.sleep < 0:
        print("--sleep no puede ser negativo", file=sys.stderr)
        return 2
    if args.retries < 0:
        print("--retries no puede ser negativo", file=sys.stderr)
        return 2
    return ejecutar_corrida(args)


if __name__ == "__main__":
    raise SystemExit(main())
