"""Evalúa la propuesta y el ADR sobre los proyectos golden (data/golden/*.yaml).

Dos modos:

* Sin argumentos: usa las salidas grabadas en cada caso (lo mismo que corre
  CI en tests/eval/test_golden_rubric.py) y muestra la tabla de la rúbrica.
* ``--live``: genera de nuevo la propuesta (con el prompt actual de
  app/core/proposal_generator.py) y la guía del ADR (prompt de
  app/core/adr_generator.py) contra un LLM real, y aplica la rúbrica. Úsalo
  cuando cambies un prompt, antes de abrir el PR.

Variables para ``--live`` (modelo compatible con OpenAI, p. ej. Groq):
  EVAL_LLM_MODEL     (default openai/gpt-oss-120b)
  EVAL_LLM_BASE_URL  (default https://api.groq.com/openai/v1)
  EVAL_LLM_API_KEY   (obligatoria)
  EVAL_WAIT_S        segundos entre casos (default 60; el plan gratuito de
                     Groq permite 8000 tokens por minuto y cada caso usa
                     2 o 3 llamadas)
  EVAL_MAX_RETRIES   reintentos ante un 429 (default 4; espera lo que pide
                     el proveedor)

Uso:
  python scripts/eval_adr_golden.py
  python scripts/eval_adr_golden.py --live --case mascotas-perdidas
  python scripts/eval_adr_golden.py --live --min-score 0.8   # exit 1 si baja
  python scripts/eval_adr_golden.py --live --complex --repeat 3

``--complex`` usa los casos de data/golden/complejos/ (proyectos grandes, sin
salidas grabadas: solo sirven con ``--live``). ``--repeat N`` corre cada caso N
veces y resume cuántas propuestas salieron completas a la primera, cuántas se
repararon y cuántas fallaron: es la medida de "tuve que regenerar".

Sale con código 1 si algún caso queda por debajo de ``--min-score``.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("EMBEDDINGS_WARMUP", "off")
# Los reintentos por 429 ocurren dentro de la llamada a la guía: con el tope
# normal de 120 s se cortaría antes de terminar de esperar.
os.environ.setdefault("ADR_LLM_TIMEOUT_S", "400")

from app.core.golden_eval import (  # noqa: E402
    GOLDEN_DIR,
    GoldenCase,
    build_context,
    evaluate_case,
    expected_checks,
    load_cases,
    select_rows,
)

COMPLEX_DIR = GOLDEN_DIR / "complejos"


def _build_model():
    from langchain.chat_models import init_chat_model

    api_key = os.getenv("EVAL_LLM_API_KEY")
    if not api_key:
        sys.exit("Falta EVAL_LLM_API_KEY para --live")
    model = init_chat_model(
        os.getenv("EVAL_LLM_MODEL", "openai/gpt-oss-120b"),
        model_provider="openai",
        base_url=os.getenv("EVAL_LLM_BASE_URL", "https://api.groq.com/openai/v1"),
        api_key=api_key,
        temperature=0.2,
    )
    return _RetryingModel(model, int(os.getenv("EVAL_MAX_RETRIES", "4")))


_RETRY_AFTER_RE = re.compile(r"try again in ([\d.]+)\s*(ms|s|m)\b", re.IGNORECASE)


class _RetryingModel:
    """Envuelve el modelo y reintenta los 429 (límite de tokens por minuto).

    Groq gratis permite 8000 tokens/min y cada caso hace 2 o 3 llamadas de
    ~5000. Sin esto un 429 cortaba la corrida entera; además, dentro de la app
    un 429 en la guía deja el ADR sin sección 7 y la rúbrica mediría eso, no
    la calidad del prompt.
    """

    def __init__(self, model, retries: int):
        self._model = model
        self._retries = retries

    async def ainvoke(self, *args, **kwargs):
        for attempt in range(self._retries + 1):
            try:
                return await self._model.ainvoke(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001 -- se filtra abajo
                text = str(exc)
                if attempt >= self._retries or ("429" not in text and "rate_limit" not in text):
                    raise
                match = _RETRY_AFTER_RE.search(text)
                wait = 30.0
                if match:
                    value, unit = float(match.group(1)), match.group(2).lower()
                    wait = value / 1000 if unit == "ms" else value * 60 if unit == "m" else value
                wait = min(max(wait + 2.0, 5.0), 120.0)
                print(f"   (límite de tokens del proveedor: espero {wait:.0f}s y reintento)", flush=True)
                await asyncio.sleep(wait)
        raise RuntimeError("sin respuesta del modelo")


def _text(message) -> str:
    content = getattr(message, "content", message)
    if isinstance(content, list):
        return "".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in content)
    return str(content or "")


async def _live_outputs(model, case: GoldenCase) -> tuple[str, str | None, str]:
    """``(propuesta, guía, estado)``; estado = ok | llm | tabla | fallo (ver repair_proposal)."""
    from app.core.adr_generator import generate_guide
    from app.core.proposal_generator import _build_prompt, _profile_kind, repair_proposal

    citations = select_rows(case)
    prompt = _build_prompt(
        citations=citations,
        prior_content=None,
        feedback=None,
        project_name=case.name,
        description=case.description,
        requirements_text=case.requirements_text,
        project_kind=_profile_kind(case.profile or None),
    )
    message = await model.ainvoke(prompt)
    proposal = _text(message)
    finish_reason = (getattr(message, "response_metadata", None) or {}).get("finish_reason")
    # Igual que en la app: si la propuesta no pasa la validación se completa
    # (pasada del LLM y, si no alcanza, tabla armada con los patrones).
    repaired, status = await repair_proposal(model, proposal, citations, finish_reason=finish_reason)
    if repaired is None:
        return proposal, None, status
    # Igual que en la app: redacción + revisión + corrección si hace falta.
    guide, _repaired = await generate_guide(model, build_context(case, repaired, citations))
    return repaired, guide, status


_STATUS_LABELS = {
    "ok": "completa a la primera",
    "llm": "reparada por el LLM",
    "tabla": "tabla armada con los patrones",
    "fallo": "INCOMPLETA (en la app habría que regenerar)",
}


def _print_result(case: GoldenCase, result, compare: bool, status: str | None = None) -> None:
    expected = expected_checks(case) if compare else {}
    print(f"\n{case.id} ({case.kind}) — {result.score * 100:.0f}%")
    if status:
        print(f"  propuesta: {_STATUS_LABELS.get(status, status)}")
    for check in result.checks:
        mark = "OK " if check.passed else "NO "
        note = ""
        if compare and check.name in expected and expected[check.name] is not check.passed:
            note = f"  <- esperado {'OK' if expected[check.name] else 'NO'}"
        print(f"  {mark}{check.name}{note}")
        if check.detail:
            print(f"       {check.detail}")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--live", action="store_true", help="generar con un LLM real")
    parser.add_argument("--case", help="solo este caso (id)")
    parser.add_argument("--min-score", type=float, default=0.0, help="puntaje mínimo por caso (0-1)")
    parser.add_argument("--complex", action="store_true", help="casos de data/golden/complejos (solo --live)")
    parser.add_argument("--repeat", type=int, default=1, help="corridas por caso (solo --live)")
    args = parser.parse_args()
    if args.complex and not args.live:
        sys.exit("--complex no tiene salidas grabadas: úsalo con --live")

    directory = COMPLEX_DIR if args.complex else None
    cases = [c for c in load_cases(directory) if not args.case or c.id == args.case]
    cases = [c for c in cases for _ in range(max(1, args.repeat if args.live else 1))]
    if not cases:
        print("No hay casos que evaluar")
        return 1

    model = _build_model() if args.live else None
    wait = float(os.getenv("EVAL_WAIT_S", "60"))
    failed = []
    statuses: list[str] = []
    for index, case in enumerate(cases):
        status = None
        if model is not None:
            if index:
                await asyncio.sleep(wait)
            try:
                proposal, guide, status = await _live_outputs(model, case)
            except Exception as exc:  # noqa: BLE001 -- un caso no corta la corrida
                print(f"\n{case.id} ({case.kind}) — ERROR: {type(exc).__name__}: {str(exc)[:200]}")
                failed.append(case.id)
                statuses.append("error")
                continue
            statuses.append(status)
            result, _md, _cit = evaluate_case(case, proposal=proposal, guide=guide)
        else:
            result, _md, _cit = evaluate_case(case)
        _print_result(case, result, compare=not args.live, status=status)
        if result.score < args.min_score or status == "fallo":
            failed.append(case.id)

    total = len(cases)
    if statuses:
        counts = {key: statuses.count(key) for key in ("ok", "llm", "tabla", "fallo", "error")}
        print(
            f"\nPropuestas: {counts['ok']} completas a la primera, "
            f"{counts['llm']} reparadas por el LLM, {counts['tabla']} con tabla armada, "
            f"{counts['fallo']} incompletas, {counts['error']} con error del proveedor"
        )
    print(f"\n{total - len(failed)}/{total} casos por encima de {args.min_score:.2f}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
