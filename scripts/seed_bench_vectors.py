#!/usr/bin/env python3
"""Siembra y mide el corpus sintético F19 en las tablas que consulta RAG.

Uso: ``python scripts/seed_bench_vectors.py [--tables all|patterns|documents]``.
Los patrones reales se mantienen con ``scripts/seed_patterns.py``. Este script
inserta chunks sintéticos, no embeddings en la tabla padre.
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


def random_unit_vectors(n: int, dim: int) -> np.ndarray:
    vectors = np.random.randn(n, dim).astype(np.float32)
    return vectors / np.linalg.norm(vectors, axis=1, keepdims=True)


def _vector(vector: np.ndarray) -> str:
    return "[" + ",".join(f"{value:.6f}" for value in vector) + "]"


def _document_owner(db) -> tuple[int, int]:
    user_id = db.execute(text("""
        INSERT INTO users (username, email, password_hash, is_demo_user)
        VALUES (:username, :email, 'benchmark-only', true)
        ON CONFLICT (username) DO UPDATE SET username=EXCLUDED.username RETURNING id
    """), {"username": BENCHMARK_USERNAME, "email": "benchmark-synthetic@example.invalid"}).scalar_one()
    project_id = db.execute(text("SELECT id FROM projects WHERE user_id=:user_id AND name=:name"), {"user_id": user_id, "name": BENCHMARK_PROJECT_NAME}).scalar()
    if project_id is None:
        project_id = db.execute(text("""
            INSERT INTO projects (user_id, name, description, is_demo)
            VALUES (:user_id, :name, 'Corpus sintético F19', true) RETURNING id
        """), {"user_id": user_id, "name": BENCHMARK_PROJECT_NAME}).scalar_one()
    return int(user_id), int(project_id)


def seed(n: int, tables: str, batch_size: int = 500) -> tuple[int | None, int | None]:
    """Inserta n vectores en cada ámbito seleccionado y devuelve user/proyecto."""
    db = SessionLocal()
    try:
        user_id = project_id = document_id = None
        if tables in {"all", "documents"}:
            user_id, project_id = _document_owner(db)
            db.execute(text("DELETE FROM uploaded_documents WHERE user_id=:user_id AND filename=:filename"), {"user_id": user_id, "filename": BENCHMARK_FILENAME})
            document_id = db.execute(text("""
                INSERT INTO uploaded_documents (user_id, project_id, filename, file_type, file_size_bytes, chunk_count, processed, version)
                VALUES (:user_id, :project_id, :filename, '.md', 0, :n, true, 1) RETURNING id
            """), {"user_id": user_id, "project_id": project_id, "filename": BENCHMARK_FILENAME, "n": n}).scalar_one()
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
                """), [{"pattern_id": pattern_id, "chunk_text": f"synthetic pattern chunk {start + index}", "embedding": _vector(vector)} for index, vector in enumerate(vectors)])
            if document_id is not None:
                db.execute(text("""
                    INSERT INTO document_chunks (document_id, chunk_text, chunk_index, embedding)
                    VALUES (:document_id, :chunk_text, :chunk_index, CAST(:embedding AS vector))
                """), [{"document_id": document_id, "chunk_text": f"synthetic document chunk {start + index}", "chunk_index": start + index, "embedding": _vector(vector)} for index, vector in enumerate(vectors)])
            db.commit()
        print(f"Insertados en {time.perf_counter() - started:.1f}s")
        return user_id, project_id
    finally:
        db.close()


def reindex(tables: str) -> None:
    indexes = (["idx_pattern_chunks_embedding"] if tables in {"all", "patterns"} else []) + (["document_chunks_embedding_idx"] if tables in {"all", "documents"} else [])
    db = SessionLocal()
    try:
        for index in indexes:
            db.execute(text(f"REINDEX INDEX {index}"))
        db.commit()
    finally:
        db.close()


def benchmark(user_id: int | None, project_id: int | None, scope: str) -> None:
    from app.core.rag import similarity_search
    queries = [f"consulta F19 distinta {number}: arquitectura resiliente" for number in range(20)]
    samples, hits = [], 0
    for index, query in enumerate(queries):
        _, metrics = similarity_search(query, user_id=user_id, project_id=project_id, k=5, scope=scope)
        if index:  # primera consulta: cold path, no se reporta
            samples.append(metrics["search_ms"])
            hits += int(bool(metrics.get("embedding_cached")))
    print("scope={} n={} p50={:.2f}ms p95={:.2f}ms cache_hits={:.1f}%".format(
        scope, len(samples), statistics.median(samples), statistics.quantiles(samples, n=100, method="inclusive")[94], hits / len(samples) * 100,
    ))


def cleanup() -> None:
    db = SessionLocal()
    try:
        # El cascade borra architect_pattern_chunks y document_chunks.
        db.execute(text("DELETE FROM architect_patterns WHERE category=:category"), {"category": BENCHMARK_CATEGORY})
        user_id = db.execute(text("SELECT id FROM users WHERE username=:username"), {"username": BENCHMARK_USERNAME}).scalar()
        if user_id is not None:
            db.execute(text("DELETE FROM uploaded_documents WHERE user_id=:user_id AND filename=:filename"), {"user_id": user_id, "filename": BENCHMARK_FILENAME})
            db.execute(text("DELETE FROM projects WHERE user_id=:user_id AND name=:name"), {"user_id": user_id, "name": BENCHMARK_PROJECT_NAME})
            # Conservamos el usuario técnico: eliminarlo podría cascada datos
            # ajenos si alguien reutilizó accidentalmente ese identificador.
        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=10_000)
    parser.add_argument("--tables", choices=("all", "patterns", "documents"), default="all")
    parser.add_argument("--scope", choices=("all", "patterns"), default="all")
    parser.add_argument("--cleanup", action="store_true")
    parser.add_argument("--skip-seed", action="store_true")
    args = parser.parse_args()
    if args.cleanup:
        cleanup(); raise SystemExit(0)
    get_embeddings()  # warm-up fuera de las mediciones
    user_id, project_id = (None, None) if args.skip_seed else seed(args.n, args.tables)
    if not args.skip_seed:
        reindex(args.tables)
    if args.scope == "all" and user_id is None:
        raise SystemExit("scope=all requiere un corpus de documentos recién sembrado")
    benchmark(user_id, project_id, args.scope)
