"""
HU8 (#14 de la revisión): volver a sembrar no borra los chunks ``source_upload``.

Usa un cursor falso, así que no necesita base de datos ni el modelo de
embeddings. ``chunk_type`` es ``NOT NULL``, de modo que el ``<>`` no deja
filas sin borrar por un ``NULL``.
"""

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import seed_patterns  # noqa: E402


class FakeCursor:
    def __init__(self):
        self.calls: list[tuple[str, tuple]] = []

    def execute(self, sql, params=()):
        self.calls.append((" ".join(sql.split()), params))


def test_reseed_keeps_source_upload_chunks(monkeypatch):
    monkeypatch.setattr(
        seed_patterns, "build_pattern_chunks", lambda pattern: {"summary": "resumen", "empty": ""}
    )
    monkeypatch.setattr(seed_patterns, "embed_passage", lambda text: [0.0, 1.0])
    cur = FakeCursor()

    created = seed_patterns.seed_pattern_chunks(cur, 7, {"pattern_name": "Monolito modular"})

    delete_sql, delete_params = cur.calls[0]
    assert delete_sql == (
        "DELETE FROM architect_pattern_chunks "
        "WHERE pattern_id = %s AND chunk_type <> 'source_upload'"
    )
    assert delete_params == (7,)
    assert not any(sql.startswith("DELETE") for sql, _ in cur.calls[1:])
    assert created == 1
