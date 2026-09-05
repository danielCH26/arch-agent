"""
Ingesta interna de fuentes PDF/MD para patrones de arquitectura.

Uso:
    python scripts/ingest_pattern_source.py --pattern-id 3 --file fuentes/event-driven.pdf
"""

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ingesta una fuente PDF/MD en architect_pattern_chunks.",
    )
    parser.add_argument("--pattern-id", type=int, required=True, help="ID del patron existente.")
    parser.add_argument("--file", required=True, help="Ruta al PDF o MD fuente.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    from app.core.document_processing import (
        ALLOWED_EXTENSIONS,
        MAX_FILE_SIZE_BYTES,
        DocumentProcessingError,
        process_file,
        validate_file_extension,
        validate_file_size,
    )
    from app.core.embeddings import get_embeddings
    from app.core.pattern_document_storage import PatternStorageError, save_pattern_chunks

    file_path = Path(args.file)
    filename = file_path.name

    if not validate_file_extension(filename):
        print(
            f"Formato no soportado. Solo: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
            file=sys.stderr,
        )
        return 1

    try:
        size_bytes = file_path.stat().st_size
    except FileNotFoundError:
        print(f"Archivo no encontrado: {file_path}", file=sys.stderr)
        return 1

    if not validate_file_size(size_bytes, MAX_FILE_SIZE_BYTES):
        print(
            f"El archivo excede el límite de {MAX_FILE_SIZE_BYTES // (1024 * 1024)} MB",
            file=sys.stderr,
        )
        return 1

    try:
        chunks = process_file(str(file_path))
        texts = [f"passage: {chunk.page_content}" for chunk in chunks]
        embeddings = get_embeddings().embed_documents(texts)
        inserted = save_pattern_chunks(
            pattern_id=args.pattern_id,
            chunks=chunks,
            embeddings=embeddings,
            filename=filename,
        )
    except DocumentProcessingError as e:
        print(str(e), file=sys.stderr)
        return 1
    except PatternStorageError as e:
        print(str(e), file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error inesperado durante la ingesta: {e}", file=sys.stderr)
        return 1

    print(
        f"Ingesta completada: {inserted} chunks insertados en pattern_id={args.pattern_id}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
