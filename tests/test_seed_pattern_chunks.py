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


class FakeConn:
    def __init__(self, rowcount):
        self.cur = FakeCursor()
        self.cur.rowcount = rowcount

    def cursor(self):
        return self.cur


def test_images_only_sync_does_not_embed_nor_delete(monkeypatch):
    """F29: el arranque del backend copia las imagenes sin recalcular embeddings."""
    patterns = [
        {
            "pattern_name": "Monolito modular",
            "image": "/pattern-images/modular_monolith.svg",
            "image_alt": "Una sola aplicacion dividida en modulos",
            "image_source": {"titulo": "Propio", "autor": "Equipo", "licencia": "X", "url": None},
        },
        {"pattern_name": "Sin imagen"},
    ]
    monkeypatch.setattr(seed_patterns, "load_patterns", lambda: patterns)

    def no_embed(_text):
        raise AssertionError("--images-only no debe cargar el modelo")

    monkeypatch.setattr(seed_patterns, "embed_passage", no_embed)
    conn = FakeConn(rowcount=1)

    updated = seed_patterns.sync_pattern_images(conn)

    assert updated == 2
    sqls = [sql for sql, _params in conn.cur.calls]
    assert all(sql.startswith("UPDATE architect_patterns SET image = %s") for sql in sqls)
    first_params = conn.cur.calls[0][1]
    assert first_params[0] == "/pattern-images/modular_monolith.svg"
    assert '"autor": "Equipo"' in first_params[2]
    assert first_params[3] == "Monolito modular"
    assert conn.cur.calls[1][1] == (None, None, None, "Sin imagen")
