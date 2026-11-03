"""
Seed de patrones de arquitectura para la base RAG.

Lee el contenido desde data/patterns/*.yaml y mantiene pobladas:
- architect_patterns, para el catalogo y compatibilidad con scripts existentes.
- architect_pattern_chunks, para busqueda semantica por contexto especifico.

Cada corrida reconcilia la tabla contra el YAML actual: cualquier fila que
no corresponda a un pattern_name presente en data/patterns/*.yaml se borra
(residuo de scripts/seed_bench_vectors.py, filas huerfanas de versiones
anteriores, etc.). Los chunks asociados se borran en cascada por el FK.

Con ``--images-only`` solo copia image / image_alt / image_source del YAML a
las filas que ya existen, sin cargar el modelo de embeddings (segundos). El
backend lo corre en cada arranque (scripts/start_backend.sh, tanto en Docker
Compose como en Railway), asi ningun entorno
queda con las columnas de la migracion 0024 vacias.
"""

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.pattern_catalog import (  # noqa: E402
    PATTERNS_DIR,
    build_pattern_chunks,
    VALID_FAMILIES,
    VALID_LEVELS,
    load_patterns as _load_catalog,
)
from seed_common import connect_db, log  # noqa: E402

# Complejidad operativa que exige cada patron (campo `complexity` del YAML).
VALID_COMPLEXITY = ("baja", "media", "alta")


def load_patterns() -> list[dict]:
    patterns = _load_catalog()
    if not patterns:
        log(f"No se encontraron archivos .yaml en {PATTERNS_DIR}", "ERROR")
        sys.exit(1)
    for pattern in patterns:
        if pattern.get("family") not in VALID_FAMILIES or pattern.get("level") not in VALID_LEVELS:
            log(
                f"{pattern['pattern_name']}: family={pattern.get('family')!r} / "
                f"level={pattern.get('level')!r} no son validos ({VALID_FAMILIES} / "
                f"{VALID_LEVELS}); la tabla de trade-offs no podra diversificar con el",
                "WARN",
            )
        if pattern.get("complexity") not in VALID_COMPLEXITY:
            log(
                f"{pattern['pattern_name']}: complexity={pattern.get('complexity')!r} "
                f"no es una de {VALID_COMPLEXITY}; ese patron no se penalizara al reordenar",
                "WARN",
            )
        if not pattern.get("image") or not pattern.get("image_alt") or not pattern.get("image_source"):
            log(
                f"{pattern['pattern_name']}: falta image / image_alt / image_source; "
                "la Base de patrones mostrara el aviso de patron sin imagen",
                "WARN",
            )
    return patterns


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
    fuentes = json.dumps(pattern.get("fuentes", []))
    image_source = json.dumps(pattern["image_source"]) if pattern.get("image_source") else None

    if row is None:
        cur.execute(
            """
            INSERT INTO architect_patterns
                (pattern_name, category, description, use_cases, tradeoffs,
                 when_not_to_use, decision_signals, complexity, fuentes,
                 image, image_alt, image_source, embedding)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector)
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
                pattern.get("complexity"),
                fuentes,
                pattern.get("image"),
                pattern.get("image_alt"),
                image_source,
                embedding,
            ),
        )
        return cur.fetchone()[0]

    cur.execute(
        """
        UPDATE architect_patterns
        SET category = %s, description = %s, use_cases = %s, tradeoffs = %s,
            when_not_to_use = %s, decision_signals = %s, complexity = %s,
            fuentes = %s, image = %s, image_alt = %s, image_source = %s,
            embedding = %s::vector
        WHERE id = %s
        """,
        (
            pattern["category"],
            pattern["description"],
            pattern["use_cases"],
            json.dumps(pattern["tradeoffs"]),
            pattern.get("when_not_to_use"),
            decision_signals,
            pattern.get("complexity"),
            fuentes,
            pattern.get("image"),
            pattern.get("image_alt"),
            image_source,
            embedding,
            row[0],
        ),
    )
    return row[0]


def seed_pattern_chunks(cur, pattern_id: int, pattern: dict) -> int:
    """Recrea los chunks indexables del patron.

    Solo borra los chunks que genera el catalogo: los ``source_upload`` vienen
    de scripts/ingest_pattern_source.py y no se pueden recrear desde el YAML.
    """
    cur.execute(
        "DELETE FROM architect_pattern_chunks "
        "WHERE pattern_id = %s AND chunk_type <> 'source_upload'",
        (pattern_id,),
    )
    # build_pattern_chunks vive en app/core/pattern_catalog.py: es la misma
    # logica que usa scripts/eval_pattern_retrieval.py, asi la evaluacion mide
    # exactamente lo que se indexa.
    candidates = build_pattern_chunks(pattern)

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


def sync_pattern_images(conn) -> int:
    """Copia la imagen y su atribucion del YAML a los patrones ya sembrados.

    No inserta ni borra patrones ni toca embeddings: eso sigue siendo el seed
    completo. Devuelve cuantas filas actualizo.
    """
    patterns = load_patterns()
    cur = conn.cursor()
    updated = 0
    for pattern in patterns:
        image_source = json.dumps(pattern["image_source"]) if pattern.get("image_source") else None
        cur.execute(
            """
            UPDATE architect_patterns
            SET image = %s, image_alt = %s, image_source = %s
            WHERE pattern_name = %s
            """,
            (pattern.get("image"), pattern.get("image_alt"), image_source, pattern["pattern_name"]),
        )
        updated += cur.rowcount
    if updated < len(patterns):
        log(
            f"Solo {updated} de {len(patterns)} patrones estan en la base: corre el seed "
            "completo (python scripts/seed_patterns.py) para cargar los que faltan",
            "WARN",
        )
    log(f"Imagenes de patrones sincronizadas: {updated}", "OK")
    return updated


def seed_patterns(conn):
    patterns = load_patterns()
    cur = conn.cursor()
    total_chunks = 0
    curated_names = [p["pattern_name"] for p in patterns]

    for pattern in patterns:
        pattern_id = upsert_pattern(cur, pattern)
        total_chunks += seed_pattern_chunks(cur, pattern_id, pattern)

    # Reconciliacion: borra todo lo que no venga del YAML actual (contaminacion
    # de scripts/seed_bench_vectors.py, filas huerfanas de versiones previas
    # del script, etc). Los chunks se borran en cascada por el FK.
    cur.execute(
        "DELETE FROM architect_patterns WHERE NOT (pattern_name = ANY(%s))",
        (curated_names,),
    )
    removed = cur.rowcount
    if removed:
        log(f"Eliminadas {removed} filas no-curadas (residuo de benchmark/versiones previas)", "WARN")

    log(f"Patrones procesados: {len(patterns)}. Chunks (re)generados: {total_chunks}", "OK")
    return len(patterns), total_chunks


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument(
        "--images-only",
        action="store_true",
        help="solo sincroniza image / image_alt / image_source (sin embeddings)",
    )
    args = parser.parse_args()

    log("=" * 60)
    log("Seed de patrones de arquitectura (architect_patterns + chunks)")
    log("=" * 60)
    conn = connect_db()
    try:
        if args.images_only:
            sync_pattern_images(conn)
        else:
            seed_patterns(conn)
        conn.commit()
    finally:
        conn.close()

    # Las convenciones de estructura de repositorio se consultan junto con los
    # patrones (el arbol de carpetas necesita las dos cosas), asi que se
    # siembran en la misma corrida. Va despues del commit y en su propio
    # try/except: si falla el seed de convenciones, los patrones ya quedaron
    # cargados y la aplicacion sigue funcionando sin el arbol de carpetas.
    log("-" * 60)
    log("Seed de convenciones de estructura (repo_convention_chunks)")
    try:
        from seed_conventions import main as seed_conventions_main

        seed_conventions_main()
    except SystemExit as exc:
        if exc.code:
            log(
                "El seed de convenciones no termino; el arbol de carpetas no "
                "estara disponible hasta que corras: "
                "python scripts/seed_conventions.py",
                "WARN",
            )
    except Exception as exc:  # pragma: no cover - defensa del arranque
        log(f"El seed de convenciones fallo: {exc}", "WARN")


if __name__ == "__main__":
    main()
