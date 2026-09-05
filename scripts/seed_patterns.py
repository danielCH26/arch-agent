"""
Seed de patrones de arquitectura para la base RAG.

Lee el contenido desde data/patterns/*.yaml y mantiene pobladas:
- architect_patterns, para el catalogo y compatibilidad con scripts existentes.
- architect_pattern_chunks, para busqueda semantica por contexto especifico.
"""

import json
import sys
from pathlib import Path

import yaml

from seed_common import connect_db, log

PATTERNS_DIR = Path(__file__).parent.parent / "data" / "patterns"


def load_patterns() -> list[dict]:
    files = sorted(PATTERNS_DIR.glob("*.yaml"))
    if not files:
        log(f"No se encontraron archivos .yaml en {PATTERNS_DIR}", "ERROR")
        sys.exit(1)
    return [yaml.safe_load(path.read_text(encoding="utf-8")) for path in files]


PATTERNS = load_patterns()

_model = None


def get_model():
    """Carga una sola vez el modelo de embeddings multilingual-e5-small."""
    global _model
    if _model is None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            log(
                "Falta la dependencia 'sentence-transformers'. Instálala con: "
                "pip install sentence-transformers",
                "ERROR",
            )
            sys.exit(1)
        log("Cargando modelo de embeddings (intfloat/multilingual-e5-small)...")
        _model = SentenceTransformer("intfloat/multilingual-e5-small")
        log("Modelo cargado", "OK")
    return _model


def embed_passage(text: str) -> list:
    """Embedding de un texto tipo documento con prefijo e5."""
    model = get_model()
    vector = model.encode(f"passage: {text}", normalize_embeddings=True)
    return vector.tolist()


def embed_query(text: str) -> list:
    """Embedding de un texto tipo consulta con prefijo e5."""
    model = get_model()
    vector = model.encode(f"query: {text}", normalize_embeddings=True)
    return vector.tolist()


def to_pgvector_literal(vector: list) -> str:
    """Convierte una lista de floats al formato literal que espera PGVector."""
    return "[" + ",".join(f"{v:.8f}" for v in vector) + "]"


def upsert_pattern(cur, pattern: dict) -> int:
    """Inserta o actualiza el patron y devuelve su id."""
    cur.execute(
        "SELECT id FROM architect_patterns WHERE pattern_name = %s",
        (pattern["pattern_name"],),
    )
    row = cur.fetchone()

    embedding_text = f"{pattern['description']} {pattern['use_cases']}"
    embedding = to_pgvector_literal(embed_passage(embedding_text))
    decision_signals = json.dumps(pattern.get("decision_signals", []))

    if row is None:
        cur.execute(
            """
            INSERT INTO architect_patterns
                (pattern_name, category, description, use_cases, tradeoffs,
                 when_not_to_use, decision_signals, embedding)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s::vector)
            RETURNING id
            """,
            (
                pattern["pattern_name"],
                pattern["category"],
                pattern["description"],
                pattern["use_cases"],
                json.dumps(pattern["tradeoffs"]),
                pattern.get("when_not_to_use"),
                decision_signals,
                embedding,
            ),
        )
        return cur.fetchone()[0]

    cur.execute(
        """
        UPDATE architect_patterns
        SET category = %s, description = %s, use_cases = %s, tradeoffs = %s,
            when_not_to_use = %s, decision_signals = %s, embedding = %s::vector
        WHERE id = %s
        """,
        (
            pattern["category"],
            pattern["description"],
            pattern["use_cases"],
            json.dumps(pattern["tradeoffs"]),
            pattern.get("when_not_to_use"),
            decision_signals,
            embedding,
            row[0],
        ),
    )
    return row[0]


def seed_pattern_chunks(cur, pattern_id: int, pattern: dict) -> int:
    """Recrea los chunks indexables del patron."""
    cur.execute("DELETE FROM architect_pattern_chunks WHERE pattern_id = %s", (pattern_id,))
    name = pattern["pattern_name"]

    tradeoffs_text = None
    if pattern.get("tradeoffs"):
        ventajas = "; ".join(pattern["tradeoffs"].get("ventajas", []))
        desventajas = "; ".join(pattern["tradeoffs"].get("desventajas", []))
        tradeoffs_text = f"{name} - ventajas: {ventajas}. Desventajas: {desventajas}."

    signals_text = None
    if pattern.get("decision_signals"):
        preguntas = "; ".join(
            f"{signal['pregunta']} -> {signal['señal_patron']}"
            for signal in pattern["decision_signals"]
        )
        signals_text = f"{name} - señales de decision: {preguntas}"

    candidates = {
        "summary": f"{name}: {pattern['description']} {pattern['use_cases']}",
        "tradeoffs": tradeoffs_text,
        "when_not_to_use": (
            f"{name} - no usar cuando: {pattern['when_not_to_use']}"
            if pattern.get("when_not_to_use")
            else None
        ),
        "decision_signals": signals_text,
    }

    created = 0
    for chunk_type, text in candidates.items():
        if not text:
            continue
        embedding = to_pgvector_literal(embed_passage(text))
        cur.execute(
            """
            INSERT INTO architect_pattern_chunks (pattern_id, chunk_type, chunk_text, embedding)
            VALUES (%s, %s, %s, %s::vector)
            """,
            (pattern_id, chunk_type, text, embedding),
        )
        created += 1
    return created


def seed_patterns(conn):
    cur = conn.cursor()
    total_chunks = 0
    for pattern in PATTERNS:
        pattern_id = upsert_pattern(cur, pattern)
        total_chunks += seed_pattern_chunks(cur, pattern_id, pattern)
    log(f"Patrones procesados: {len(PATTERNS)}. Chunks (re)generados: {total_chunks}", "OK")
    return len(PATTERNS), total_chunks


def main():
    log("=" * 60)
    log("Seed de patrones de arquitectura (architect_patterns + chunks)")
    log("=" * 60)
    conn = connect_db()
    try:
        seed_patterns(conn)
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
