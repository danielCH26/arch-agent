"""Regression tests for the Postgres attachments lookup (F13, REQ-ATT-2).

These tests guard the BLOCKER found in PR #104 (review by Soomri, 2026-10-09):
``Message.attachments`` is declared as ``JSON().with_variant(JSONB(),
"postgresql")``. The previous lookup used ``Message.attachments.contains([...])``
which, when compiled against the Postgres dialect, emits a generic-JSON
``LIKE '%%' || x::JSONB || '%%'`` clause (because ``.contains()`` is resolved
against the declared type, not the dialect variant). That crashes in
Postgres 16 with ``invalid input syntax for type json — Token "%" is invalid``
and gets caught by ``SQLAlchemyError`` → 404 for ANY attachment. The test
suite passes because SQLite takes the other branch.

These tests pin the corrected behavior: the Postgres branch must compile to
JSONB containment (``@>``) and never ``LIKE``. They do not require a live
Postgres connection — they use SQLAlchemy's dialect compiler.
"""

from __future__ import annotations

from sqlalchemy import type_coerce
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import JSONB

from app.models.message import Message


def _compile(clause) -> str:
    """Compile ``clause`` against the Postgres dialect.

    We deliberately avoid ``literal_binds=True`` because the JSON/JSONB
    types do not ship a literal renderer in SQLAlchemy 2.0 — the bound
    parameter is enough to verify which operator is selected.
    """
    return str(clause.compile(dialect=postgresql.dialect()))


def test_buggy_attachments_contains_emits_like_on_postgres():
    """Witness the bug. Compiling ``Message.attachments.contains([...])``
    against Postgres produces ``LIKE '%%' || x::JSONB || '%%'`` — which
    crashes with ``invalid input syntax for type json — Token "%" is
    invalid`` against a real Postgres 16. This test pins the failure mode
    so a future revert that drops the ``type_coerce`` wrapper is caught
    immediately.
    """
    clause = Message.attachments.contains([{"id": "att-x"}])
    compiled = _compile(clause)

    assert "LIKE" in compiled.upper(), (
        f"Expected LIKE in the buggy compiled SQL; if SQLAlchemy now "
        f"auto-coerces to JSONB @>, this assertion becomes a no-op. "
        f"Got: {compiled!r}"
    )
    assert "@>" not in compiled, (
        f"JSONB @> must NOT appear in the buggy clause: {compiled!r}"
    )


def test_type_coerce_jsonb_contains_emits_at_arrow_on_postgres():
    """The fix: wrap ``Message.attachments`` in ``type_coerce(..., JSONB)``
    before ``.contains(...)``. The compiled SQL must contain the JSONB
    ``@>`` operator and must NOT contain ``LIKE``.
    """
    clause = type_coerce(Message.attachments, JSONB).contains(
        [{"id": "att-x"}]
    )
    compiled = _compile(clause)

    assert "@>" in compiled, f"Expected JSONB @> operator, got: {compiled!r}"
    assert "LIKE" not in compiled.upper(), (
        f"LIKE must not appear in the compiled Postgres query: {compiled!r}"
    )


def test_attachment_lookup_helper_uses_jsonb_on_postgres(monkeypatch):
    """End-to-end shape check: invoking ``_lookup_attachment`` against a
    stub session whose ``bind.dialect.name == "postgresql"`` must build a
    query whose ``Message.attachments.contains(...)`` condition compiles
    to JSONB ``@>``.
    """
    from app.api import attachments as attachments_module

    captured: dict[str, object] = {}

    class _FakeBind:
        class dialect:
            name = "postgresql"

    class _FakeQuery:
        def filter(self, *clauses):
            captured["clauses"] = clauses
            return self

        def first(self):
            return None  # exercises the "no row" path; we only inspect clauses.

    class _FakeSession:
        bind = _FakeBind()

        def query(self, model):
            captured["model"] = model
            return _FakeQuery()

    attachments_module._lookup_attachment(
        _FakeSession(), user_id=1, attachment_id="att-x"
    )

    clauses = captured.get("clauses") or ()
    assert clauses, "Expected at least one filter clause"

    saw_jsonb_contains = False
    saw_like_fallback = False
    for clause in clauses:
        try:
            compiled = _compile(clause)
        except Exception:
            continue
        if "attachments" not in compiled:
            continue
        if "@>" in compiled:
            saw_jsonb_contains = True
            assert "LIKE" not in compiled.upper(), (
                f"LIKE present alongside @> in: {compiled!r}"
            )
        elif "LIKE" in compiled.upper():
            saw_like_fallback = True

    assert saw_jsonb_contains, (
        "The attachments filter clause must compile to JSONB @> on "
        f"Postgres; captured clauses compiled: "
        f"{[_compile(c) for c in clauses]}"
    )
    assert not saw_like_fallback, (
        "Attachments filter must not fall back to LIKE on Postgres — that "
        "is the original C3 blocker."
    )