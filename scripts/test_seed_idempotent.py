"""
Test de idempotencia del seed (M2, revisión de PR "Caso de ejemplo (seed)").

Corre seed_patterns y seed_example dos veces seguidas y confirma que la
segunda corrida no duplica nada: mismos conteos de patrones, mismo
usuario/proyecto/sesión demo, mismas 4 fases aprobadas en `approvals`.
"""

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import seed_example  # noqa: E402
import seed_patterns  # noqa: E402
from _db_utils import connect_db  # noqa: E402


def _count_patterns(conn) -> int:
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM architect_patterns")
    return cur.fetchone()[0]


def _count_approvals(conn, session_id: int) -> int:
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM approvals WHERE session_id = %s", (session_id,))
    return cur.fetchone()[0]


def test_seed_patterns_is_idempotent():
    conn = connect_db()
    try:
        seed_patterns.seed_patterns(conn)
        first_count = _count_patterns(conn)

        seed_patterns.seed_patterns(conn)
        second_count = _count_patterns(conn)

        assert first_count == len(seed_patterns.PATTERNS)
        assert second_count == first_count, (
            "seed_patterns() no debe insertar duplicados en una segunda corrida"
        )
    finally:
        conn.close()


def test_seed_example_is_idempotent():
    conn = connect_db()
    try:
        project_id_1, user_id_1, session_id_1 = seed_example.seed_example_project(conn)
        seed_example.verify_end_to_end(conn, project_id_1, user_id_1, session_id_1)
        approvals_after_first_run = _count_approvals(conn, session_id_1)

        project_id_2, user_id_2, session_id_2 = seed_example.seed_example_project(conn)

        assert project_id_2 == project_id_1, (
            "una segunda corrida no debe crear un proyecto demo duplicado"
        )
        assert user_id_2 == user_id_1, (
            "una segunda corrida no debe crear un usuario demo duplicado"
        )
        assert session_id_2 == session_id_1, (
            "una segunda corrida no debe crear una sesión demo duplicada"
        )

        approvals_after_second_run = _count_approvals(conn, session_id_1)
        assert approvals_after_second_run == approvals_after_first_run, (
            "record_approval() no debe insertar aprobaciones duplicadas en approvals"
        )

        seed_example.verify_end_to_end(conn, project_id_2, user_id_2, session_id_2)
    finally:
        conn.close()