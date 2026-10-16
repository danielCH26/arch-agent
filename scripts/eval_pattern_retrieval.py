"""
Evalua el retrieval de patrones SIN base de datos.

Embebe en memoria los chunks de data/patterns/*.yaml (la misma logica que el
seed: app/core/pattern_catalog.py), corre los casos de
data/eval/pattern_retrieval_cases.yaml y reporta top-1 / top-3.

Dos modos:
  embedding  ranking por mejor chunk de cada patron (similitud pura)
  full       pasa por _select_citations (penalizacion por complejidad, reglas de
             escala, senal "no usar"): lo mismo que ve la propuesta, salvo el
             re-ranking con LLM, que necesita un modelo en linea.

Uso:
    python scripts/eval_pattern_retrieval.py
    python scripts/eval_pattern_retrieval.py --mode embedding -v
    python scripts/eval_pattern_retrieval.py --model intfloat/multilingual-e5-base
    python scripts/eval_pattern_retrieval.py --model BAAI/bge-m3 --query-prefix "" --passage-prefix ""
    python scripts/eval_pattern_retrieval.py --model lexical      # baseline sin descargas

Para decidir si vale la pena cambiar de modelo de embeddings: corre el mismo
set con --model <candidato> y compara. Si no mejora top-1/top-3, no migres.
"""

from __future__ import annotations

import argparse
import hashlib
import math
import os
import re
import sys
import unicodedata
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("DATABASE_URL", "postgresql://eval:eval@localhost:5432/eval")

from app.core.pattern_catalog import build_pattern_chunks, load_patterns  # noqa: E402

DEFAULT_CASES = PROJECT_ROOT / "data" / "eval" / "pattern_retrieval_cases.yaml"
CANDIDATE_CHUNKS = int(os.getenv("PROPOSAL_RAG_CANDIDATE_CHUNKS", "40"))


class LexicalEncoder:
    """Baseline sin descargas: bolsa de palabras hasheada (sin semantica)."""

    DIM = 1024

    @staticmethod
    def _tokens(text: str) -> list[str]:
        folded = "".join(
            c for c in unicodedata.normalize("NFD", text.casefold()) if unicodedata.category(c) != "Mn"
        )
        return [t for t in re.findall(r"[a-z0-9]{3,}", folded)]

    def encode(self, texts: list[str]) -> list[list[float]]:
        out = []
        for text in texts:
            vec = [0.0] * self.DIM
            for token in self._tokens(text):
                vec[int(hashlib.md5(token.encode()).hexdigest(), 16) % self.DIM] += 1.0
            vec = [math.log1p(v) for v in vec]
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            out.append([v / norm for v in vec])
        return out


class SentenceEncoder:
    def __init__(self, name: str) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            sys.exit("Falta sentence-transformers: pip install sentence-transformers")
        self.model = SentenceTransformer(name)

    def encode(self, texts: list[str]) -> list[list[float]]:
        return self.model.encode(texts, normalize_embeddings=True, show_progress_bar=False).tolist()


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def rank_case(case, patterns, chunk_rows, chunk_vecs, encoder, query_prefix, mode):
    from langchain_core.documents import Document

    query_vec = encoder.encode([f"{query_prefix}{case['descripcion']}"])[0]
    scored = sorted(
        ((1.0 - _dot(query_vec, vec), row) for vec, row in zip(chunk_vecs, chunk_rows)),
        key=lambda item: item[0],
    )[:CANDIDATE_CHUNKS]
    docs = [
        Document(
            page_content=row["text"],
            metadata={
                "source_type": "architect_pattern",
                "pattern_id": row["pattern_id"],
                "pattern_name": row["pattern"]["pattern_name"],
                "category": row["pattern"]["category"],
                "tradeoffs": row["pattern"].get("tradeoffs"),
                "complexity": row["pattern"].get("complexity"),
                "chunk_type": row["chunk_type"],
                "distance": dist,
                "similarity": 1.0 - dist,
            },
        )
        for dist, row in scored
    ]
    if mode == "full":
        from app.core.proposal_generator import _select_citations

        cites = _select_citations(
            docs, top_n=len(patterns), min_similarity=0.0, explicit_text=case["descripcion"]
        )
        return [c["pattern_name"] for c in cites]
    best: dict[str, float] = {}
    for doc in docs:
        if doc.metadata["chunk_type"] == "when_not_to_use":
            continue
        name = doc.metadata["pattern_name"]
        best[name] = max(best.get(name, 0.0), doc.metadata["similarity"])
    return [name for name, _ in sorted(best.items(), key=lambda kv: -kv[1])]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", default="intfloat/multilingual-e5-small")
    parser.add_argument("--query-prefix", default="query: ")
    parser.add_argument("--passage-prefix", default="passage: ")
    parser.add_argument("--mode", choices=("embedding", "full"), default="full")
    parser.add_argument("--cases", default=str(DEFAULT_CASES))
    parser.add_argument("--min-top1", type=float, default=None, help="falla (exit 1) si top-1 flexible queda por debajo (0-1)")
    parser.add_argument("--min-top3", type=float, default=None, help="falla (exit 1) si top-3 queda por debajo (0-1)")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    patterns = load_patterns()
    names = {p["pattern_name"] for p in patterns}
    cases = yaml.safe_load(Path(args.cases).read_text(encoding="utf-8"))
    for case in cases:
        unknown = [n for n in [case["esperado"], *case.get("aceptables", [])] if n not in names]
        if unknown:
            sys.exit(f"Caso {case['id']}: patrones inexistentes en data/patterns: {unknown}")

    encoder = LexicalEncoder() if args.model == "lexical" else SentenceEncoder(args.model)
    prefix = "" if args.model == "lexical" else args.passage_prefix
    query_prefix = "" if args.model == "lexical" else args.query_prefix

    chunk_rows = [
        {"pattern_id": i, "pattern": pattern, "chunk_type": kind, "text": text}
        for i, pattern in enumerate(patterns, start=1)
        for kind, text in build_pattern_chunks(pattern).items()
    ]
    chunk_vecs = encoder.encode([f"{prefix}{row['text']}" for row in chunk_rows])

    strict = flexible = top3 = 0
    print(f"modelo={args.model} modo={args.mode} patrones={len(patterns)} chunks={len(chunk_rows)} casos={len(cases)}\n")
    for case in cases:
        ranking = rank_case(case, patterns, chunk_rows, chunk_vecs, encoder, query_prefix, args.mode)
        ok = {case["esperado"], *case.get("aceptables", [])}
        got = ranking[0] if ranking else None
        hit_strict = got == case["esperado"]
        hit_flex = got in ok
        hit_top3 = any(name in ok for name in ranking[:3])
        strict += hit_strict
        flexible += hit_flex
        top3 += hit_top3
        mark = "OK " if hit_flex else ("t3 " if hit_top3 else "XX ")
        print(f"{mark}{case['id']:<30} -> {got}")
        if args.verbose or not hit_flex:
            print(f"      esperado: {case['esperado']}")
            print(f"      top-3:    {ranking[:3]}")
    n = len(cases)
    print(
        f"\ntop-1 estricto: {strict}/{n} ({strict / n:.0%})   "
        f"top-1 flexible: {flexible}/{n} ({flexible / n:.0%})   top-3: {top3}/{n} ({top3 / n:.0%})"
    )
    if args.min_top1 is not None and flexible / n < args.min_top1:
        return 1
    if args.min_top3 is not None and top3 / n < args.min_top3:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
