#!/usr/bin/env python3
"""
Benchmark del Criterio 3: tiempo de busqueda < 100ms para 10k vectores.

Inserta ~10,000 patrones SINTETICOS con vectores aleatorios normalizados
(384d, para matchear multilingual-e5-small) directamente por SQL -- no usa
el modelo de embeddings real porque generar 10k embeddings en CPU es lento
y no aporta nada a esta prueba puntual (aqui medimos velocidad del indice
ivfflat, no relevancia semantica; eso ya se prueba en el Criterio 1 con
datos reales).

Todos los registros sinteticos quedan marcados con category='benchmark-synthetic'
para poder limpiarlos despues sin tocar los patrones reales sembrados por
scripts/seed_architect_patterns.py.

Uso:
    docker compose exec backend python scripts/seed_bench_vectors.py            # carga 10k + mide
    docker compose exec backend python scripts/seed_bench_vectors.py --n 20000  # otro volumen
    docker compose exec backend python scripts/seed_bench_vectors.py --cleanup  # borra solo los sinteticos
"""

from __future__ import annotations

import argparse
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


def random_unit_vectors(n: int, dim: int) -> np.ndarray:
    """Vectores aleatorios normalizados (norma 1), igual que hace el
    modelo real con normalize_embeddings=True -- asi la distancia coseno
    que usa ivfflat se comporta de forma comparable a datos reales."""
    vectors = np.random.randn(n, dim).astype(np.float32)
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    return vectors / norms


def seed(n: int, batch_size: int = 500) -> None:
    print(f"Insertando {n} patrones sinteticos ({EMBEDDING_DIM}d)...")
    db = SessionLocal()
    try:
        inserted = 0
        t0 = time.perf_counter()
        for start in range(0, n, batch_size):
            batch_n = min(batch_size, n - start)
            vectors = random_unit_vectors(batch_n, EMBEDDING_DIM)
            rows = [
                {
                    "pattern_name": f"__bench_pattern_{start + i}",
                    "category": BENCHMARK_CATEGORY,
                    "description": "Vector sintetico para benchmark de performance.",
                    "embedding": "[" + ",".join(f"{x:.6f}" for x in vec) + "]",
                }
                for i, vec in enumerate(vectors)
            ]
            db.execute(
                text(
                    """
                    INSERT INTO architect_patterns
                        (pattern_name, category, description, embedding)
                    VALUES
                        (:pattern_name, :category, :description, CAST(:embedding AS vector))
                    """
                ),
                rows,
            )
            db.commit()
            inserted += batch_n
            print(f"  {inserted}/{n}", end="\r")
        print(f"\nInsertados {inserted} en {time.perf_counter() - t0:.1f}s")
    finally:
        db.close()


def reindex() -> None:
    """El indice ivfflat se construye con las listas calculadas para el
    volumen que tenia la tabla al momento de crearlo (ver schema.sql).
    Si la tabla crecio mucho desde entonces (como aca, +10k filas), hay
    que REINDEX para que el planner lo use bien."""
    print("Reindexando idx_architect_patterns_embedding...")
    db = SessionLocal()
    try:
        db.execute(text("REINDEX INDEX idx_architect_patterns_embedding"))
        db.commit()
    finally:
        db.close()


def benchmark(rounds: int = 10) -> None:
    from app.core.rag import similarity_search

    print(f"\nEjecutando {rounds} busquedas de prueba...\n")
    queries = [
        "arquitectura de microservicios independientes",
        "como implemento CQRS y event sourcing",
        "seguridad y autenticacion en APIs",
        "escalado horizontal de servicios",
        "patrones de resiliencia y circuit breaker",
    ]

    search_times = []
    for i in range(rounds):
        query = queries[i % len(queries)]
        _docs, metrics = similarity_search(
            query=query, user_id=None, project_id=None, k=5, scope="patterns"
        )
        search_times.append(metrics["search_ms"])
        print(f"  [{i + 1:2d}] query={query[:40]:<40} search_ms={metrics['search_ms']:.2f}")

    avg = sum(search_times) / len(search_times)
    p95 = sorted(search_times)[int(len(search_times) * 0.95) - 1]
    print(f"\nsearch_ms -> avg={avg:.2f}ms  min={min(search_times):.2f}ms  "
          f"max={max(search_times):.2f}ms  p95={p95:.2f}ms")

    if max(search_times) < 100:
        print("\n✅ CRITERIO 3 CUMPLIDO: todas las busquedas < 100ms")
    else:
        over = [t for t in search_times if t >= 100]
        print(f"\n❌ CRITERIO 3 NO CUMPLIDO: {len(over)}/{rounds} busquedas >= 100ms")


def cleanup() -> None:
    print("Borrando patrones sinteticos de benchmark...")
    db = SessionLocal()
    try:
        result = db.execute(
            text("DELETE FROM architect_patterns WHERE category = :cat"),
            {"cat": BENCHMARK_CATEGORY},
        )
        db.commit()
        print(f"Borrados {result.rowcount} registros sinteticos.")
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=10_000, help="Cantidad de vectores a insertar")
    parser.add_argument("--rounds", type=int, default=10, help="Cantidad de busquedas a medir")
    parser.add_argument("--cleanup", action="store_true", help="Solo borra los datos sinteticos y sale")
    parser.add_argument("--skip-seed", action="store_true", help="No insertar, solo medir (si ya sembraste antes)")
    args = parser.parse_args()

    if args.cleanup:
        cleanup()
        sys.exit(0)

    # Toca get_embeddings() una vez antes para que el modelo real (usado
    # por similarity_search al vectorizar la QUERY) ya este cacheado y no
    # infle el primer tiempo medido.
    get_embeddings()

    if not args.skip_seed:
        seed(args.n)
        reindex()

    benchmark(args.rounds)

    print("\nPara limpiar los datos sinteticos despues:")
    print("  docker compose exec backend python scripts/seed_bench_vectors.py --cleanup")
