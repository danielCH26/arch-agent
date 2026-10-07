"""
Structural tests for SQL migration files.

These tests pin the on-disk SQL that ships with the repo: they catch
typos, accidental drops, and renames of well-known migrations. They do
NOT execute the SQL -- that requires a live Postgres and lives in
the integration suite (gated by DATABASE_URL_ASISTENTE_REAL).

Issue surfaced during PR #76 cleanup (verify-report.md §Deviations
#1): the GIN index migration 0013 ships the Postgres containment
branch but no test exercised it. This file is the cheap pin: it
catches the obvious regressions (file deleted, IF NOT EXISTS
removed, target column renamed) without requiring a database.
"""

from __future__ import annotations

from pathlib import Path

import pytest

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"


def _read(name: str) -> str:
    path = MIGRATIONS_DIR / name
    if not path.exists():
        pytest.fail(f"Migration file missing: {path}")
    return path.read_text(encoding="utf-8")


class Test0013GinIndex:
    """Pin the GIN index migration that backs the C3 fix (Postgres
    containment branch in app/api/attachments.py:_lookup_attachment)."""

    def test_file_exists_with_expected_name(self):
        # Filename is part of the public contract: the migration runner
        # applies files in numeric order, and other migrations/scripts
        # reference this name by string. Renames need a coordinated
        # update.
        path = MIGRATIONS_DIR / "0013_add_message_attachments_gin_index.sql"
        assert path.exists(), f"expected migration file at {path}"

    def test_creates_gin_index_with_idempotent_guard(self):
        sql = _read("0013_add_message_attachments_gin_index.sql")
        # IF NOT EXISTS is the guard that makes the migration safe to
        # re-run, and the runner relies on it for idempotency.
        assert "CREATE INDEX IF NOT EXISTS" in sql
        # The opclass is the whole point of this migration: a GIN
        # index on messages.attachments with jsonb_path_ops.
        assert "USING GIN" in sql
        assert "jsonb_path_ops" in sql

    def test_targets_messages_attachments_column(self):
        # The lookup is "messages WHERE user_id = ? AND attachments
        # @> '[{id: ...}]'::jsonb". The index must be on the
        # attachments column of the messages table for the planner
        # to use it.
        sql = _read("0013_add_message_attachments_gin_index.sql")
        assert "ON messages" in sql
        assert "attachments" in sql

    def test_create_index_statement_omits_concurrently(self):
        # CONCURRENTLY cannot run inside a transaction block, and
        # scripts/run_migrations.py applies each file in its own
        # transaction. The migration intentionally omits CONCURRENTLY
        # from the DDL to keep the runner simple. If this changes,
        # the runner needs to be updated first -- this test forces
        # the conversation.
        #
        # We strip SQL line comments ("-- ...") before the check so
        # the migration can still discuss CONCURRENTLY in its header
        # without tripping the assertion. The point is the keyword
        # in the DDL, not the prose.
        sql = _read("0013_add_message_attachments_gin_index.sql")
        non_comment = "\n".join(
            line for line in sql.splitlines() if not line.lstrip().startswith("--")
        )
        assert "CONCURRENTLY" not in non_comment.upper()
