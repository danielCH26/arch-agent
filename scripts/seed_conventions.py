"""
Seed de las convenciones de estructura de repositorio en el RAG.

Lee data/conventions/*.yaml y mantiene poblada `repo_convention_chunks`, que
es una categoría NUEVA del RAG: no toca `architect_patterns` ni sus chunks.

Cada corrida reconcilia la tabla contra el YAML: las convenciones que ya no
estén en el catálogo se borran, las nuevas se insertan y las existentes se
actualizan. Así renombrar o quitar una convención no deja basura buscable.

Se puede correr suelto:

    python scripts/seed_conventions.py

o dejar que `scripts/seed_patterns.py` lo llame al final, que es lo que pasa
en el arranque normal: las convenciones y los patrones se consultan juntos y
conviene que se siembren juntos.
"""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.convention_catalog import (  # noqa: E402
    catalog_documents,
    list_conventions,
)
from app.core.pattern_catalog import (  # noqa: E402
    KNOWN_UNCOVERED_MODULE_KINDS,
    module_kinds_without_patterns,
)
from seed_common import connect_db, log  # noqa: E402

_model = None


def get_model():
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
    return get_model().encode(f"passage: {text}", normalize_embeddings=True).tolist()


def to_pgvector_literal(vector: list) -> str:
    return "[" + ",".join(f"{v:.8f}" for v in vector) + "]"


def report_coverage() -> None:
    """Avisa qué tipos de módulo no tienen patrón aplicable.

    No es fatal: el generador del árbol reporta esos módulos como "sin patrón
    aplicable" en lugar de inventarle uno. Pero conviene verlo acá, en el
    arranque, y no descubrirlo en mitad de una demo.
    """
    faltantes = sorted(module_kinds_without_patterns())
    conocidos = sorted(KNOWN_UNCOVERED_MODULE_KINDS)
    if not faltantes:
        log("Cobertura de patrones por tipo de módulo: completa", "OK")
        return
    nivel = "WARN" if faltantes == conocidos else "ERROR"
    log(
        f"{len(faltantes)} tipo(s) de módulo sin patrón aplicable: "
        + ", ".join(faltantes),
        nivel,
    )
    if faltantes != conocidos:
        log(
            "La lista cambió respecto a KNOWN_UNCOVERED_MODULE_KINDS en "
            "app/core/pattern_catalog.py; actualízala o etiqueta el patrón "
            "que falta con applies_to_modules.",
            "ERROR",
        )


def main() -> None:
    conventions = list_conventions()
    if not conventions:
        log(
            "El catálogo de convenciones está vacío. ¿Existe data/conventions/ "
            "con al menos un YAML válido?",
            "ERROR",
        )
        sys.exit(1)
    log(
        "Convenciones: "
        + ", ".join(f"{c.name} [{c.layer}]" for c in conventions)
    )
    report_coverage()

    documents = list(catalog_documents())
    if not documents:
        log("El catálogo no produjo documentos; nada que indexar.", "ERROR")
        sys.exit(1)

    conn = connect_db()
    cur = conn.cursor()

    cur.execute("SELECT to_regclass('public.repo_convention_chunks')")
    if cur.fetchone()[0] is None:
        log(
            "No existe la tabla repo_convention_chunks. Corre primero: "
            "python migrations/run_migrations.py",
            "ERROR",
        )
        sys.exit(1)

    vigentes: list[str] = []
    for _key, text, meta in documents:
        convention_id = meta["convention_id"]
        vigentes.append(convention_id)
        embedding = to_pgvector_literal(embed_passage(text))
        cur.execute(
            """
            INSERT INTO repo_convention_chunks
                (convention_id, name, layer, chunk_text, embedding, chunk_metadata)
            VALUES (%s, %s, %s, %s, %s::vector, %s)
            ON CONFLICT (convention_id) DO UPDATE SET
                name           = EXCLUDED.name,
                layer          = EXCLUDED.layer,
                chunk_text     = EXCLUDED.chunk_text,
                embedding      = EXCLUDED.embedding,
                chunk_metadata = EXCLUDED.chunk_metadata
            """,
            (
                convention_id,
                meta["name"],
                meta["layer"],
                text,
                embedding,
                json.dumps(meta),
            ),
        )

    # Reconciliación: fuera lo que ya no está en el YAML.
    cur.execute("SELECT convention_id FROM repo_convention_chunks")
    existentes = {row[0] for row in cur.fetchall()}
    sobrantes = existentes - set(vigentes)
    for convention_id in sorted(sobrantes):
        cur.execute(
            "DELETE FROM repo_convention_chunks WHERE convention_id = %s",
            (convention_id,),
        )
    if sobrantes:
        log(f"{len(sobrantes)} convención(es) obsoleta(s) eliminada(s)", "OK")

    conn.commit()
    cur.execute("SELECT layer, COUNT(*) FROM repo_convention_chunks GROUP BY layer")
    for layer, count in sorted(cur.fetchall()):
        log(f"{layer}: {count} convención(es) indexada(s)", "OK")
    cur.close()
    conn.close()
    log("Convenciones de estructura cargadas en el RAG", "OK")


if __name__ == "__main__":
    main()
