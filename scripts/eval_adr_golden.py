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
  EVAL_WAIT_S        segundos entre casos (default 20; el plan gratuito de
                     Groq permite 8000 tokens por minuto)

Uso:
  python scripts/eval_adr_golden.py
  python scripts/eval_adr_golden.py --live --case mascotas-perdidas
  python scripts/eval_adr_golden.py --live --min-score 0.8   # exit 1 si baja

Sale con código 1 si algún caso queda por debajo de ``--min-score``.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("EMBEDDINGS_WARMUP", "off")

from app.core.golden_eval import (  # noqa: E402
    GoldenCase,
    build_context,
    evaluate_case,
    expected_checks,
    load_cases,
    select_rows,
)


def _build_model():
    from langchain.chat_models import init_chat_model

    api_key = os.getenv("EVAL_LLM_API_KEY")
    if not api_key:
        sys.exit("Falta EVAL_LLM_API_KEY para --live")
    return init_chat_model(
        os.getenv("EVAL_LLM_MODEL", "openai/gpt-oss-120b"),
        model_provider="openai",
        base_url=os.getenv("EVAL_LLM_BASE_URL", "https://api.groq.com/openai/v1"),
        api_key=api_key,
        temperature=0.2,
    )


def _text(message) -> str:
    content = getattr(message, "content", message)
    if isinstance(content, list):
        return "".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in content)
    return str(content or "")


async def _live_outputs(model, case: GoldenCase) -> tuple[str, str | None]:
    from app.core.adr_generator import generate_llm_sections
    from app.core.proposal_generator import _build_prompt, _profile_kind

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
    proposal = _text(await model.ainvoke(prompt))
    guide = await generate_llm_sections(model, build_context(case, proposal, citations))
    return proposal, guide


def _print_result(case: GoldenCase, result, compare: bool) -> None:
    expected = expected_checks(case) if compare else {}
    print(f"\n{case.id} ({case.kind}) — {result.score * 100:.0f}%")
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
    args = parser.parse_args()

    cases = [c for c in load_cases() if not args.case or c.id == args.case]
    if not cases:
        print("No hay casos que evaluar")
        return 1

    model = _build_model() if args.live else None
    wait = float(os.getenv("EVAL_WAIT_S", "20"))
    failed = []
    for index, case in enumerate(cases):
        if model is not None:
            if index:
                await asyncio.sleep(wait)
            proposal, guide = await _live_outputs(model, case)
            result, _md, _cit = evaluate_case(case, proposal=proposal, guide=guide)
        else:
            result, _md, _cit = evaluate_case(case)
        _print_result(case, result, compare=not args.live)
        if result.score < args.min_score:
            failed.append(case.id)

    total = len(cases)
    print(f"\n{total - len(failed)}/{total} casos por encima de {args.min_score:.2f}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
