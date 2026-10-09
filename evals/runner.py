"""
Harness del golden set: mide la variabilidad real de las propuestas de arquitectura.

El scorer (``score_output``) es determinista y puro: no hace red, no toca la base
de datos y no llama a un LLM. Eso lo hace testeable offline en CI.

El runner de ejecucion arma el prompt con la funcion REAL de produccion
(``app.core.proposal_generator._build_prompt``). Nunca se copia el texto del
prompt aqui: si el prompt de produccion cambia, el golden set se entera solo.

Uso rapido:
    python -m evals.runner --dry-run
    python -m evals.runner --models gpt-oss-120b --repeats 5

Variables de entorno (mismos nombres que ``smoke_test_tool_calling.py``):
    LLM_BASE_URL   p.ej. https://api.groq.com/openai/v1
    LLM_API_KEY    clave del proveedor
    LLM_MODEL      modelo por defecto si no se pasa --models
"""

from __future__ import annotations

import argparse
import itertools
import json
import os
import re
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

# Dependencias de solo stdlib + pyyaml en este nivel, para que ``--dry-run`` y
# los tests unitarios no dependan de langchain ni de la configuracion de la app.
import yaml

# --- Contrato del prompt de produccion ---------------------------------------
# Estos tres encabezados son los literales de ``_build_prompt`` (en espanol,
# con la tilde en "Tecnologias"). El prompt de produccion usa la forma con
# tilde; el harness la refleja exactamente para que medir el contrato del
# modelo no tenga desviaciones por "correccion" del scorer.
SECCIONES_REQUERIDAS: tuple[str, ...] = ("Componentes", "Tecnologías", "Patrones")

RUTA_CASES = Path(__file__).with_name("cases.yaml")
RUTA_RESULTADOS = Path(__file__).with_name("results")

# Espera base entre llamadas. El free tier de Groq son 30 RPM (2 s por request),
# asi que 2.2 s deja margen. Ajustar con --sleep si el proveedor lo permite.
SLEEP_POR_DEFECTO = 2.2


# =============================================================================
# Scorer puro
# =============================================================================

_RE_HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
_RE_MARCADOR = re.compile(r"\[(\d+)\]")
_RE_BULLET = re.compile(r"^\s*[-*]\s+\S")


def _normalizar_heading(texto: str) -> str:
    """Compara encabezados ignorando mayusculas y espacios sobrantes.

    NO normaliza acentos: el prompt pide ``Tecnologías`` con tilde y eso es
    parte del contrato que se quiere medir.
    """
    return " ".join(texto.strip().split()).casefold()


def _headings(markdown: str) -> list[tuple[int, int, str]]:
    """Devuelve ``(indice_linea, nivel, texto)`` de cada encabezado markdown."""
    encontrados: list[tuple[int, int, str]] = []
    for indice, linea in enumerate(markdown.splitlines()):
        match = _RE_HEADING.match(linea)
        if match:
            encontrados.append((indice, len(match.group(1)), match.group(2).strip()))
    return encontrados


def marcadores_cita(markdown: str) -> list[int]:
    """Indices numericos ``[N]`` citados en el texto, en orden de aparicion.

    Solo acepta numeros: un enlace markdown como ``[Componentes](#seccion)`` no
    es una cita y no debe contarse.
    """
    return [int(n) for n in _RE_MARCADOR.findall(markdown)]


def score_output(markdown: str, caso: dict) -> dict[str, Any]:
    """Puntua una propuesta generada contra el caso del golden set.

    Funcion pura: no hace red, no usa DB, no llama al LLM.

    Returns:
        dict con ``secciones_ok``, ``orden_ok``, ``sin_secciones_extra``,
        ``citas_validas``, ``bullets_por_seccion``, ``largo``, ``marcadores`` y
        ``pass_estructural``.
    """
    markdown = markdown or ""
    citas = caso.get("citations") or []
    total_citas = len(citas)
    requeridas = {_normalizar_heading(s) for s in SECCIONES_REQUERIDAS}

    headings = _headings(markdown)
    de_nivel_2 = [(i, t) for i, nivel, t in headings if nivel == 2]

    # Presencia de cada seccion obligatoria (primera aparicion).
    primera: dict[str, int] = {}
    duplicadas: list[str] = []
    for indice, texto in de_nivel_2:
        clave = _normalizar_heading(texto)
        if clave in requeridas:
            if clave in primera:
                duplicadas.append(texto)
            else:
                primera[clave] = indice

    secciones_ok = all(_normalizar_heading(s) in primera for s in SECCIONES_REQUERIDAS)

    orden_ok = False
    if secciones_ok:
        orden = [primera[_normalizar_heading(s)] for s in SECCIONES_REQUERIDAS]
        orden_ok = orden == sorted(orden) and len(set(orden)) == len(orden)

    # Un encabezado `##` es "extra" si su texto no es una de las secciones
    # obligatorias. Repetir una obligatoria no cuenta como extra, pero se
    # reporta aparte en `secciones_duplicadas`.
    extras = [t for _, t in de_nivel_2 if _normalizar_heading(t) not in requeridas]
    sin_secciones_extra = not extras

    # Citas: todos los marcadores [N] deben caer dentro del rango provisto.
    # Con citations vacias, cualquier marcador es invalido (fallo esperado del
    # modelo, no del scorer).
    marcadores = marcadores_cita(markdown)
    fuera_de_rango = [n for n in marcadores if n < 1 or n > total_citas]
    citas_validas = not fuera_de_rango

    # Bullets por seccion: cuenta de lineas con "- " o "* " dentro del tramo
    # que va desde el encabezado de la seccion hasta el siguiente `##`.
    bullets_por_seccion: dict[str, int] = {}
    for seccion in SECCIONES_REQUERIDAS:
        clave = _normalizar_heading(seccion)
        if clave not in primera:
            bullets_por_seccion[seccion] = 0
            continue
        inicio = primera[clave]
        fin = len(markdown.splitlines())
        for indice, _ in de_nivel_2:
            if indice > inicio:
                fin = indice
                break
        lineas = markdown.splitlines()[inicio + 1 : fin]
        bullets_por_seccion[seccion] = sum(1 for l in lineas if _RE_BULLET.match(l))

    pass_estructural = bool(
        secciones_ok and orden_ok and sin_secciones_extra and citas_validas
    )

    return {
        "secciones_ok": secciones_ok,
        "orden_ok": orden_ok,
        "sin_secciones_extra": sin_secciones_extra,
        "citas_validas": citas_validas,
        "pass_estructural": pass_estructural,
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
    """Lee ``cases.yaml`` y valida el schema minimo de cada caso."""
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

        citations = caso.get("citations")
        if citations is None:
            caso["citations"] = []
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

    return casos


def dry_run(casos: list[dict]) -> int:
    """Valida el corpus e imprime el detalle. No necesita API key ni DB."""
    print(f"Casos cargados: {len(casos)}\n")
    print(
        f"{'id':<12} {'proyecto':<26} {'citas':>5}  {'desc':>5}  nombre"
    )
    print("-" * 100)
    for caso in casos:
        print(
            f"{caso['id']:<12} {caso['project_name']:<26} "
            f"{len(caso['citations']):>5}  {len(caso['descripcion']):>5}  "
            f"{caso['nombre']}"
        )

    sin_citas = [c["id"] for c in casos if not c["citations"]]
    print()
    print(f"Casos con citations: [] -> {len(sin_citas)} ({', '.join(sin_citas) or '-'})")
    print(
        f"Secciones obligatorias: {', '.join(SECCIONES_REQUERIDAS)} "
        f"(comparacion estricta, sin normalizar acentos)"
    )

    # Verificacion obligatoria del prompt real: confirma que el harness
    # puede construir el prompt que mandaria al LLM. Si falla, NO es un
    # "AVISO" silencioso: el runner nunca podra ejecutar este caso, asi
    # que el dry-run debe fallar loud (exit code != 0). Antes del fix B1
    # la llamada tenia un quinto argumento que la firma no aceptaba, asi
    # que cada invocacion levantaba TypeError, el except lo tragaba y el
    # dry-run reportaba 0 con un mensaje de "AVISO" -- falso verde.
    from app.core.proposal_generator import _build_prompt

    try:
        muestra = _build_prompt(
            casos[0]["citations"],
            None,
            None,
            casos[0]["project_name"],
        )
    except Exception as exc:  # noqa: BLE001 -- queremos reportar y abortar
        print(
            f"\n[ERROR] No se pudo construir el prompt con _build_prompt: {exc}",
            file=sys.stderr,
        )
        return 1
    print(f"\n_build_prompt importado OK. Muestra ({len(muestra)} caracteres):")
    print("-" * 60)
    print(muestra)

    print("\n[OK] Corpus valido. No se realizo ninguna llamada de red.")
    return 0


# =============================================================================
# Metricas de variabilidad
# =============================================================================


def _jaccard(a: set[int], b: set[int]) -> float:
    """Jaccard de dos conjuntos de marcadores. Dos vacios = 1.0 (coinciden)."""
    if not a and not b:
        return 1.0
    union = a | b
    if not union:
        return 1.0
    return len(a & b) / len(union)


def calcular_variabilidad(
    ejecuciones: list[dict], caso_id: str, modelo: str
) -> dict[str, Any]:
    """Agrega los repeats de un mismo (caso, modelo) en metricas de variabilidad.

    Solo entra lo que salio bien; los fallos se excluyen del calculo.
    """
    exitosas = [
        e
        for e in ejecuciones
        if e.get("ok") and e["caso_id"] == caso_id and e["modelo"] == modelo
    ]
    n = len(exitosas)
    resumen: dict[str, Any] = {
        "caso_id": caso_id,
        "modelo": modelo,
        "repeats_ok": n,
        "repeats_fallidos": sum(
            1
            for e in ejecuciones
            if not e.get("ok") and e["caso_id"] == caso_id and e["modelo"] == modelo
        ),
        "tasa_exacta": None,
        "acuerdo_estructural": None,
        "solapamiento_citas": None,
        "desvio_largo": 0.0,
        "largo_medio": 0.0,
    }
    if n == 0:
        return resumen

    largos = [e["score"]["largo"] for e in exitosas]
    resumen["largo_medio"] = statistics.fmean(largos)
    resumen["desvio_largo"] = statistics.pstdev(largos) if n > 1 else 0.0
    resumen["tasa_pas_estructural"] = (
        statistics.fmean(1.0 if e["score"]["pass_estructural"] else 0.0 for e in exitosas)
    )

    if n < 2:
        return resumen

    pares = list(itertools.combinations(range(n), 2))
    resumen["tasa_exacta"] = statistics.fmean(
        1.0 if exitosas[i]["markdown"] == exitosas[j]["markdown"] else 0.0
        for i, j in pares
    )
    resumen["acuerdo_estructural"] = statistics.fmean(
        1.0
        if exitosas[i]["score"]["pass_estructural"]
        == exitosas[j]["score"]["pass_estructural"]
        else 0.0
        for i, j in pares
    )
    resumen["solapamiento_citas"] = statistics.fmean(
        _jaccard(
            set(exitosas[i]["score"]["marcadores"]),
            set(exitosas[j]["score"]["marcadores"]),
        )
        for i, j in pares
    )
    return resumen


def resumir_por_modelo(variabilidad: list[dict], ejecuciones: list[dict]) -> dict:
    """Medias de cada métrica, agrupadas por modelo, sobre todos los casos."""
    modelos = sorted({v["modelo"] for v in variabilidad})
    resumen: dict[str, Any] = {}
    for modelo in modelos:
        filas = [v for v in variabilidad if v["modelo"] == modelo]
        propias = [
            e for e in ejecuciones if e.get("ok") and e["modelo"] == modelo
        ]

        def _media(clave: str) -> float | None:
            valores = [f[clave] for f in filas if f.get(clave) is not None]
            return statistics.fmean(valores) if valores else None

        resumen[modelo] = {
            "casos": len(filas),
            "ejecuciones_ok": len(propias),
            "ejecuciones_fallidas": sum(
                1 for e in ejecuciones if not e.get("ok") and e["modelo"] == modelo
            ),
            "tasa_pas_estructural": (
                statistics.fmean(
                    1.0 if e["score"]["pass_estructural"] else 0.0 for e in propias
                )
                if propias
                else None
            ),
            "tasa_exacta": _media("tasa_exacta"),
            "acuerdo_estructural": _media("acuerdo_estructural"),
            "solapamiento_citas": _media("solapamiento_citas"),
            "desvio_largo": _media("desvio_largo"),
        }
    return resumen


# =============================================================================
# Runner de ejecucion
# =============================================================================


def construir_modelo(modelo: str, base_url: str, api_key: str, temperature: float):
    """Construye el modelo LangChain igual que lo hace la app en produccion.

    La app fija ``temperature`` via ``DEFAULT_LLM_TEMPERATURE`` (0.0) en
    ``app/core/llm_loader.py``; aca queda parametrizable para poder medir como
    se comporta el corpus con otros valores. La construccion del modelo (y la
    omision de ``temperature`` para la serie ``o*``) se delega a
    ``_build_chat_model`` para no duplicar la regla y reventar con un 400 si
    el corpus incluye razonadores.
    """
    from app.core.llm_loader import _build_chat_model

    return _build_chat_model(
        model=modelo,
        base_url=base_url,
        api_key=api_key,
        temperature=temperature,
    )


def _es_rate_limit(exc: Exception) -> bool:
    """Detecta 429 sin depender del SDK del proveedor."""
    texto = str(exc).lower()
    return "429" in texto or "rate limit" in texto or "too many requests" in texto


def ejecutar_corrida(args: argparse.Namespace) -> int:
    """Corre el golden set completo. Un caso que falla no aborta la corrida."""
    from app.core.proposal_generator import _build_prompt

    casos = cargar_casos()
    por_id = {c["id"]: c for c in casos}
    casos_seleccionados = [por_id[cid] for cid in args.case] if args.case else casos

    base_url = os.getenv("LLM_BASE_URL", "").strip()
    api_key = os.getenv("LLM_API_KEY", "").strip()

    faltantes = [
        nombre
        for nombre, valor in (("LLM_BASE_URL", base_url), ("LLM_API_KEY", api_key))
        if not valor
    ]
    if faltantes:
        print(
            "Faltan variables de entorno: "
            + ", ".join(faltantes)
            + "\nDefinelas o usa --dry-run para validar el corpus sin red.",
            file=sys.stderr,
        )
        return 2

    modelos = args.models.split(",") if args.models else [os.getenv("LLM_MODEL", "")]
    modelos = [m.strip() for m in modelos if m.strip()]
    if not modelos:
        print("Falta LLM_MODEL o --models", file=sys.stderr)
        return 2

    print(f"Proveedor : {base_url}")
    print(f"Modelos   : {', '.join(modelos)}")
    print(f"Casos     : {len(casos_seleccionados)}")
    print(f"Repeats   : {args.repeats}")
    print(f"Temperatura: {args.temperature}")
    print(f"Espera    : {args.sleep}s entre llamadas")
    total = len(casos_seleccionados) * len(modelos) * args.repeats
    print(f"Total de invocaciones: {total}\n")

    ejecuciones: list[dict] = []
    for modelo in modelos:
        try:
            chat = construir_modelo(modelo, base_url, api_key, args.temperature)
        except Exception as exc:  # noqa: BLE001 -- un modelo malo no corta todo
            print(f"[ERROR] No se pudo construir el modelo '{modelo}': {exc}\n")
            continue

        for caso in casos_seleccionados:
            for repeat in range(1, args.repeats + 1):
                marca = f"[{caso['id']} | {modelo} | repeat {repeat}/{args.repeats}]"
                try:
                    prompt = _build_prompt(
                        caso["citations"],
                        None,
                        None,
                        caso["project_name"],
                    )
                except Exception as exc:  # noqa: BLE001
                    print(f"{marca} ERROR al armar el prompt: {exc}")
                    ejecuciones.append(
                        {
                            "caso_id": caso["id"],
                            "modelo": modelo,
                            "repeat": repeat,
                            "ok": False,
                            "error": f"prompt: {exc}",
                        }
                    )
                    continue

                try:
                    started = time.perf_counter()
                    respuesta = chat.invoke(prompt)
                    markdown = _contenido(respuesta)
                    ms = int((time.perf_counter() - started) * 1000)
                    score = score_output(markdown, caso)
                    ejecuciones.append(
                        {
                            "caso_id": caso["id"],
                            "modelo": modelo,
                            "repeat": repeat,
                            "ok": True,
                            "latencia_ms": ms,
                            "markdown": markdown,
                            "score": score,
                        }
                    )
                    estado = "OK " if score["pass_estructural"] else "KO "
                    print(
                        f"{marca} {estado} {score['largo']:>5} chars  "
                        f"{ms:>6} ms  "
                        f"secciones={score['secciones_ok']} orden={score['orden_ok']} "
                        f"citas={score['citas_validas']} extra={score['secciones_extra']}"
                    )
                except Exception as exc:  # noqa: BLE001 -- seguir ante 429/500/timeout
                    mensaje = f"{type(exc).__name__}: {exc}"
                    print(f"{marca} FALLO: {mensaje[:160]}")
                    ejecuciones.append(
                        {
                            "caso_id": caso["id"],
                            "modelo": modelo,
                            "repeat": repeat,
                            "ok": False,
                            "error": mensaje,
                        }
                    )
                    if _es_rate_limit(exc):
                        # Backoff: no repetir la invocacion, solo esperar mas
                        # antes de la siguiente para no encadenar 429.
                        espera_extra = args.sleep * 2
                        print(f"    rate limit: esperando {espera_extra:.1f}s")
                        time.sleep(espera_extra)
                        continue

                if not args.dry_run and args.sleep > 0:
                    time.sleep(args.sleep)

    variabilidad = [
        calcular_variabilidad(ejecuciones, caso["id"], modelo)
        for modelo in modelos
        for caso in casos_seleccionados
    ]
    resumen = resumir_por_modelo(variabilidad, ejecuciones)

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    RUTA_RESULTADOS.mkdir(parents=True, exist_ok=True)
    ruta_json = RUTA_RESULTADOS / f"{timestamp}.json"
    ruta_json.write_text(
        json.dumps(
            {
                "metadata": {
                    "timestamp": timestamp,
                    "base_url": base_url,
                    "modelos": modelos,
                    "repeats": args.repeats,
                    "temperature": args.temperature,
                    "sleep_s": args.sleep,
                    "secciones_requeridas": list(SECCIONES_REQUERIDAS),
                },
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

    # Exit code: 0 si al menos una invocacion dio "ok"; 1 si TODAS
    # fallaron. Asi CI puede distinguir "corri pero el LLM dio 0" de
    # "nunca llego a ejecutarse". Antes del fix B1 el runner llegaba aca
    # con ``ejecuciones`` lleno de fallos ``prompt: ...`` y devolvia 0
    # igual -- el harness reportaba "OK" midiendo nada.
    exitosos = sum(1 for e in ejecuciones if e.get("ok"))
    if exitosos == 0 and ejecuciones:
        print(
            "\n[ERROR] Todas las invocaciones fallaron. "
            "Revisar errores arriba.",
            file=sys.stderr,
        )
        return 1
    return 0


def _contenido(respuesta: Any) -> str:
    """Normaliza la respuesta del chat a texto plano."""
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
    return str(contenido)


def _fmt(valor: float | None, decimales: int = 3) -> str:
    if valor is None:
        return "   n/d"
    return f"{valor:.{decimales}f}"


def _filtrar_peores(variabilidad: list[dict]) -> dict:
    """Particiona ``variabilidad`` en pares con variabilidad observada y pares sin datos.

    La regla original (``(v.get("tasa_exacta") or 1.0) < 1.0``) excluia
    silenciosamente los pares con ``tasa_exacta is None``: cuando todos
    los repeats fallaron, ``None or 1.0 == 1.0`` y el par quedaba fuera
    del listado -- al reves de lo util para diagnosticar. Esta funcion
    separa los dos grupos para que ``_imprimir_resumen`` los muestre
    como secciones distintas.

    Returns:
        ``{"peor": [...], "all_failed": [...]}``. Las dos listas son
        disjuntas: ``peor`` tiene tasa_exacta entre [0.0, 1.0); ``all_failed``
        tiene tasa_exacta == None (0 o 1 repeats_ok). Los pares con
        tasa_exacta == 1.0 (perfectamente reproducibles) no aparecen en
        ninguna.
    """
    peor = [
        v for v in variabilidad
        if v.get("tasa_exacta") is not None and v["tasa_exacta"] < 1.0
    ]
    all_failed = [v for v in variabilidad if v.get("tasa_exacta") is None]
    return {"peor": peor, "all_failed": all_failed}


def _imprimir_resumen(
    resumen: dict,
    variabilidad: list[dict],
    ejecuciones: list[dict],
    ruta_json: Path,
) -> None:
    print("\n" + "=" * 78)
    print("RESUMEN POR MODELO")
    print("=" * 78)
    print(
        f"{'modelo':<28} {'struct_ok':>10} {'exacta':>8} {'acuerdo':>9} "
        f"{'citas':>7} {'desv_lg':>9} {'fallos':>7}"
    )
    print("-" * 78)
    for modelo, stats in resumen.items():
        print(
            f"{modelo:<28} {_fmt(stats['tasa_pas_estructural']):>10} "
            f"{_fmt(stats['tasa_exacta']):>8} {_fmt(stats['acuerdo_estructural']):>9} "
            f"{_fmt(stats['solapamiento_citas']):>7} "
            f"{_fmt(stats['desvio_largo'], 1):>9} {stats['ejecuciones_fallidas']:>7}"
        )
    print()
    print("struct_ok  = tasa de salidas que pasan el chequeo estructural completo")
    print("exacta     = fraccion de pares de repeats identicos byte a byte")
    print("acuerdo    = fraccion de pares con el mismo pass_estructural")
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
    peor = grupos["peor"]
    all_failed = grupos["all_failed"]
    if peor:
        print(f"\nPares (caso, modelo) con al menos un repeat distinto: {len(peor)}")
        for v in peor:
            print(
                f"  - {v['caso_id']:<13} {v['modelo']:<24} "
                f"exacta={_fmt(v['tasa_exacta'])} "
                f"acuerdo={_fmt(v['acuerdo_estructural'])} "
                f"desv_lg={_fmt(v['desvio_largo'], 1)}"
            )
    if all_failed:
        print(
            f"\nEjecuciones con todos los repeats fallidos (sin variabilidad "
            f"calculable): {len(all_failed)}"
        )
        for v in all_failed:
            print(
                f"  - {v['caso_id']:<13} {v['modelo']:<24} "
                f"repeats_ok={v.get('repeats_ok', 0)} "
                f"repeats_fallidos={v.get('repeats_fallidos', 0)}"
            )

    print(f"\nDetalle completo: {ruta_json}")


# =============================================================================
# CLI
# =============================================================================


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m evals.runner",
        description="Mide la variabilidad de las propuestas de arquitectura.",
    )
    parser.add_argument(
        "--models",
        help="Modelos a comparar, separados por coma. Si se omite usa LLM_MODEL.",
    )
    parser.add_argument(
        "--repeats",
        type=int,
        default=3,
        help="Repeticiones del mismo caso para medir variabilidad (default: 3).",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.0,
        help=(
            "Temperatura de muestreo (default: 0).Coincide con "
            "DEFAULT_LLM_TEMPERATURE de app/core/llm_loader.py, que es lo que "
            "usa produccion."
        ),
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=SLEEP_POR_DEFECTO,
        help=f"Segundos entre llamadas (default: {SLEEP_POR_DEFECTO}).",
    )
    parser.add_argument(
        "--case",
        action="append",
        metavar="ID",
        help="Ejecutar solo estos casos. Repetible.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Valida el corpus y lista los casos. No llama a la API.",
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
    if args.repeats < 1:
        print("--repeats debe ser >= 1", file=sys.stderr)
        return 2
    if args.sleep < 0:
        print("--sleep no puede ser negativo", file=sys.stderr)
        return 2
    if args.dry_run:
        return dry_run(cargar_casos())
    return ejecutar_corrida(args)


if __name__ == "__main__":
    raise SystemExit(main())
