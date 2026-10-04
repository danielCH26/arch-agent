#!/usr/bin/env python3
"""Siembra y mide el corpus sintético F19 en las tablas que consulta RAG.

Uso::

    python scripts/seed_bench_vectors.py                      # siembra 10k + mide
    python scripts/seed_bench_vectors.py --skip-seed          # solo mide (corpus ya sembrado)
    RAG_EMBEDDING_CACHE_SIZE=0 python scripts/seed_bench_vectors.py --skip-seed   # baseline
    python scripts/seed_bench_vectors.py --cleanup            # borra lo sintético

Los patrones reales se mantienen con ``scripts/seed_patterns.py``. Este script
inserta chunks sintéticos en ``architect_pattern_chunks`` y ``document_chunks``
(las tablas que consulta ``app.core.rag``), no embeddings en la tabla padre.
Usar una base de pruebas: los patrones sintéticos aparecen en ``/api/patterns``.

La medición hace dos pasadas con las mismas 20 consultas:
  1. distintas: la primera se descarta (cold path); sin cache hits.
  2. repetidas: mide el efecto de ``RAG_EMBEDDING_CACHE_SIZE`` (≈100 % hits con
     caché activa, 0 % con ``RAG_EMBEDDING_CACHE_SIZE=0``).
Se reportan p50/p95 de ``search_ms``, ``embedding_ms`` y ``total_ms``.
"""
from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import numpy as np
from sqlalchemy import text

from app.core.database import SessionLocal
from app.core.embeddings import EMBEDDING_DIM, get_embeddings

BENCHMARK_CATEGORY = "benchmark-synthetic"
BENCHMARK_USERNAME = "__benchmark_synthetic__"
BENCHMARK_PROJECT_NAME = "__benchmark_synthetic__"
BENCHMARK_FILENAME = "__benchmark_synthetic__.md"
BENCHMARK_QUERIES = [f"consulta F19 distinta {number}: arquitectura resiliente" for number in range(20)]


def random_unit_vectors(n: int, dim: int) -> np.ndarray:
    vectors = np.random.randn(n, dim).astype(np.float32)
    return vectors / np.linalg.norm(vectors, axis=1, keepdims=True)


def _vector(vector: np.ndarray) -> str:
    return "[" + ",".join(f"{value:.6f}" for value in vector) + "]"


def _document_owner(db) -> tuple[int, int]:
    user_id = db.execute(text("""
        INSERT INTO users (username, email, password_hash, is_demo_user)
        VALUES (:username, :email, 'benchmark-only', true)
        ON CONFLICT (username) DO UPDATE SET username = EXCLUDED.username RETURNING id
    """), {"username": BENCHMARK_USERNAME, "email": "benchmark-synthetic@example.invalid"}).scalar_one()
    project_id = db.execute(
        text("SELECT id FROM projects WHERE user_id = :user_id AND name = :name"),
        {"user_id": user_id, "name": BENCHMARK_PROJECT_NAME},
    ).scalar()
    if project_id is None:
        project_id = db.execute(text("""
            INSERT INTO projects (user_id, name, description, is_demo)
            VALUES (:user_id, :name, 'Corpus sintético F19', true) RETURNING id
        """), {"user_id": user_id, "name": BENCHMARK_PROJECT_NAME}).scalar_one()
    return int(user_id), int(project_id)


def find_existing_owner() -> tuple[int, int] | None:
    """Usuario/proyecto sintéticos de una siembra previa (para --skip-seed)."""
    db = SessionLocal()
    try:
        row = db.execute(text("""
            SELECT u.id, p.id FROM users u
            JOIN projects p ON p.user_id = u.id AND p.name = :project
            WHERE u.username = :username
        """), {"username": BENCHMARK_USERNAME, "project": BENCHMARK_PROJECT_NAME}).first()
        return (int(row[0]), int(row[1])) if row else None
    finally:
        db.close()


def seed(n: int, tables: str, batch_size: int = 500) -> tuple[int | None, int | None]:
    """Inserta n vectores en cada ámbito seleccionado y devuelve user/proyecto.

    Es idempotente: borra primero el corpus sintético previo del mismo ámbito,
    para que re-ejecutar no duplique las filas.
    """
    db = SessionLocal()
    try:
        user_id = project_id = document_id = None
        if tables in {"all", "patterns"}:
            db.execute(
                text("DELETE FROM architect_patterns WHERE category = :category"),
                {"category": BENCHMARK_CATEGORY},
            )
        if tables in {"all", "documents"}:
            user_id, project_id = _document_owner(db)
            db.execute(
                text("DELETE FROM uploaded_documents WHERE user_id = :user_id AND filename = :filename"),
                {"user_id": user_id, "filename": BENCHMARK_FILENAME},
            )
            document_id = db.execute(text("""
                INSERT INTO uploaded_documents
                    (user_id, project_id, filename, file_type, file_size_bytes, chunk_count, processed, version)
                VALUES (:user_id, :project_id, :filename, '.md', 0, :n, true, 1) RETURNING id
            """), {"user_id": user_id, "project_id": project_id, "filename": BENCHMARK_FILENAME, "n": n}).scalar_one()
        db.commit()

        print(f"Insertando {n} vectores sintéticos en {tables} ({EMBEDDING_DIM}d)...")
        started = time.perf_counter()
        for start in range(0, n, batch_size):
            vectors = random_unit_vectors(min(batch_size, n - start), EMBEDDING_DIM)
            if tables in {"all", "patterns"}:
                pattern_id = db.execute(text("""
                    INSERT INTO architect_patterns (pattern_name, category, description)
                    VALUES (:name, :category, 'Corpus sintético F19') RETURNING id
                """), {"name": f"__bench_pattern_{start}", "category": BENCHMARK_CATEGORY}).scalar_one()
                db.execute(text("""
                    INSERT INTO architect_pattern_chunks (pattern_id, chunk_type, chunk_text, embedding)
                    VALUES (:pattern_id, 'benchmark', :chunk_text, CAST(:embedding AS vector))
                """), [
                    {"pattern_id": pattern_id, "chunk_text": f"synthetic pattern chunk {start + i}", "embedding": _vector(v)}
                    for i, v in enumerate(vectors)
                ])
            if document_id is not None:
                db.execute(text("""
                    INSERT INTO document_chunks (document_id, chunk_text, chunk_index, embedding)
                    VALUES (:document_id, :chunk_text, :chunk_index, CAST(:embedding AS vector))
                """), [
                    {"document_id": document_id, "chunk_text": f"synthetic document chunk {start + i}",
                     "chunk_index": start + i, "embedding": _vector(v)}
                    for i, v in enumerate(vectors)
                ])
            db.commit()
        print(f"Insertados en {time.perf_counter() - started:.1f}s")
        return user_id, project_id
    finally:
        db.close()


def reindex(tables: str) -> None:
    indexes = []
    if tables in {"all", "patterns"}:
        indexes.append("idx_pattern_chunks_embedding")
    if tables in {"all", "documents"}:
        indexes.append("document_chunks_embedding_idx")
    db = SessionLocal()
    try:
        for index in indexes:
            db.execute(text(f"REINDEX INDEX {index}"))
        db.commit()
    finally:
        db.close()


def _p(samples: list[float], pct: int) -> float:
    if len(samples) < 2:
        return samples[0] if samples else 0.0
    return statistics.quantiles(samples, n=100, method="inclusive")[pct - 1]


def _report(label: str, scope: str, rows: list[dict]) -> None:
    hits = sum(1 for r in rows if r.get("embedding_cached"))
    parts = []
    for key in ("search_ms", "embedding_ms", "total_ms"):
        values = [r[key] for r in rows]
        parts.append(f"{key} p50={statistics.median(values):.2f} p95={_p(values, 95):.2f}")
    print(f"[{label}] scope={scope} n={len(rows)} " + " | ".join(parts)
          + f" | cache_hits={hits / len(rows) * 100:.0f}%")


def benchmark(user_id: int | None, project_id: int | None, scope: str) -> None:
    from app.core import rag

    rag.clear_embedding_cache()

    def run(query: str) -> dict:
        _, metrics = rag.similarity_search(query, user_id=user_id, project_id=project_id, k=5, scope=scope)
        return metrics

    # Pasada 1: consultas distintas. La primera es cold path y no se reporta.
    distinct = [run(query) for query in BENCHMARK_QUERIES][1:]
    _report("distintas", scope, distinct)
    # Pasada 2: mismas consultas. Aquí se ve el efecto de la caché de embeddings.
    repeated = [run(query) for query in BENCHMARK_QUERIES]
    _report("repetidas", scope, repeated)

    worst = max(r["search_ms"] for r in distinct + repeated)
    verdict = "CUMPLE" if _p([r["search_ms"] for r in distinct + repeated], 95) < 100 else "NO CUMPLE"
    print(f"search_ms máx={worst:.2f}ms; p95 global {verdict} el target < 100 ms")


def cleanup() -> None:
    db = SessionLocal()
    try:
        # El cascade borra architect_pattern_chunks y document_chunks.
        db.execute(text("DELETE FROM architect_patterns WHERE category = :category"), {"category": BENCHMARK_CATEGORY})
        user_id = db.execute(
            text("SELECT id FROM users WHERE username = :username"), {"username": BENCHMARK_USERNAME}
        ).scalar()
        if user_id is not None:
            db.execute(
                text("DELETE FROM uploaded_documents WHERE user_id = :user_id AND filename = :filename"),
                {"user_id": user_id, "filename": BENCHMARK_FILENAME},
            )
            db.execute(
                text("DELETE FROM projects WHERE user_id = :user_id AND name = :name"),
                {"user_id": user_id, "name": BENCHMARK_PROJECT_NAME},
            )
            # Se conserva el usuario técnico: borrarlo podría cascadear datos
            # ajenos si alguien reutilizó ese identificador.
        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--n", type=int, default=10_000, help="vectores por tabla sembrada")
    parser.add_argument("--tables", choices=("all", "patterns", "documents"), default="all",
                        help="tablas a sembrar (default: all)")
    parser.add_argument("--scope", choices=("all", "patterns", "documents"), default=None,
                        help="scope a medir (default: all si hay corpus de documentos, si no patterns)")
    parser.add_argument("--cleanup", action="store_true", help="borra solo el corpus sintético y sale")
    parser.add_argument("--skip-seed", action="store_true", help="no sembrar; medir el corpus ya existente")
    args = parser.parse_args()

    if args.cleanup:
        cleanup()
        raise SystemExit(0)

    get_embeddings()  # warm-up fuera de las mediciones

    if args.skip_seed:
        owner = find_existing_owner()
        user_id, project_id = owner if owner else (None, None)
    else:
        user_id, project_id = seed(args.n, args.tables)
        reindex(args.tables)

    scope = args.scope or ("all" if user_id is not None else "patterns")
    if scope in {"all", "documents"} and user_id is None:
        raise SystemExit(
            f"scope={scope} requiere el corpus de documentos sintético: "
            "ejecutá sin --skip-seed (con --tables all|documents) o medí con --scope patterns"
        )
    benchmark(user_id, project_id, scope)
