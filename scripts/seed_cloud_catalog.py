"""
Seed del catálogo de servicios de nube en el RAG.

Lee data/cloud/*.yaml y mantiene poblada `cloud_service_chunks`, que es una
categoría NUEVA del RAG: no toca `architect_patterns` ni sus chunks.

Cada corrida reconcilia la tabla contra el YAML: los servicios que ya no
estén en el catálogo se borran, los nuevos se insertan y los existentes se
actualizan. Así renombrar o quitar un servicio del YAML no deja basura
buscable.

Correr:
    python scripts/seed_cloud_catalog.py
"""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.cloud_catalog import (  # noqa: E402
    catalog_documents,
    list_providers,
    missing_icons,
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


def main() -> None:
    providers = list_providers()
    log(
        "Catálogo: "
        + ", ".join(f"{p.name} ({len(p.services)} servicios)" for p in providers)
    )

    faltantes = missing_icons()
    if faltantes:
        # No es fatal: el diagrama dibuja un glifo de reserva. Pero conviene
        # saberlo acá y no descubrirlo en mitad de la demo.
        log(
            f"{len(faltantes)} servicio(s) sin PNG en data/cloud/icons/: "
            + ", ".join(faltantes),
            "WARN",
        )

    documents = list(catalog_documents())
    if not documents:
        log("El catálogo no produjo documentos; nada que indexar.", "ERROR")
        sys.exit(1)

    conn = connect_db()
    cur = conn.cursor()

    # ¿Está la tabla? Si no, falta correr las migraciones.
    cur.execute("SELECT to_regclass('public.cloud_service_chunks')")
    if cur.fetchone()[0] is None:
        log(
            "No existe la tabla cloud_service_chunks. Corre primero: "
            "python migrations/run_migrations.py",
            "ERROR",
        )
        sys.exit(1)

    vigentes: list[tuple[str, str]] = []
    for _key, text, meta in documents:
        provider = meta["provider"]
        service_id = meta["service_id"]
        vigentes.append((provider, service_id))
        embedding = to_pgvector_literal(embed_passage(text))
        cur.execute(
            """
            INSERT INTO cloud_service_chunks
                (provider, service_id, service_name, category, chunk_text,
                 embedding, chunk_metadata)
            VALUES (%s, %s, %s, %s, %s, %s::vector, %s)
            ON CONFLICT (provider, service_id) DO UPDATE SET
                service_name   = EXCLUDED.service_name,
                category       = EXCLUDED.category,
                chunk_text     = EXCLUDED.chunk_text,
                embedding      = EXCLUDED.embedding,
                chunk_metadata = EXCLUDED.chunk_metadata
            """,
            (
                provider,
                service_id,
                meta["service_name"],
                meta["category"],
                text,
                embedding,
                json.dumps(meta),
            ),
        )

    # Reconciliación: fuera lo que ya no está en el YAML.
    cur.execute("SELECT provider, service_id FROM cloud_service_chunks")
    existentes = {(row[0], row[1]) for row in cur.fetchall()}
    sobrantes = existentes - set(vigentes)
    for provider, service_id in sorted(sobrantes):
        cur.execute(
            "DELETE FROM cloud_service_chunks WHERE provider = %s AND service_id = %s",
            (provider, service_id),
        )
    if sobrantes:
        log(f"{len(sobrantes)} servicio(s) obsoleto(s) eliminado(s)", "OK")

    conn.commit()
    cur.execute("SELECT provider, COUNT(*) FROM cloud_service_chunks GROUP BY provider")
    for provider, count in sorted(cur.fetchall()):
        log(f"{provider}: {count} servicios indexados", "OK")
    cur.close()
    conn.close()
    log("Catálogo de nube cargado en el RAG", "OK")


if __name__ == "__main__":
    main()
