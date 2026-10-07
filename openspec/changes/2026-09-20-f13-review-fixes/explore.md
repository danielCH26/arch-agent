# Exploration: F13 PR #76 Review Fixes

## Change
- **Name**: `2026-09-20-f13-review-fixes`
- **Branch**: `feature/integration-f11-f12-f13` (same base as PR #76)
- **Delivery**: `delivery_strategy: single-pr`, fix commits on top of PR #76

---

## 1. Current State Analysis

### C1 — Byte Cap (2 MB): NOT IMPLEMENTED

**Confirmed absent.** After full-text search of the entire repo:

```
rg -rn "PUPPETEER_MAX_RENDER_BYTES|2097152|byte_cap" arch-agent/ --type py
→ ZERO matches
```

- `PUPPETEER_MAX_RENDER_BYTES` is never defined as a constant anywhere in the codebase.
- The `puppeteer_byte_cap` sub-reason exists in `PuppeteerUnavailable.__doc__` (`puppeteer_mcp.py:147`) but is **never raised** — no code path produces it.
- The verify-report.md §3 claims "byte cap server-side path is wired but the dedicated unit test is missing" — this is **factually incorrect**. There is no server-side byte cap path. The `PUPPETEER_MAX_RENDER_BYTES` env var appears in design.md §2.2's env table but was never codified as a Python constant.
- The **only** per-call budget wired today is `asyncio.wait_for(timeout=15.0)` at `puppeteer_mcp.py:286`.

**Implication**: REQ-PMCP-3's 2 MB byte cap is a dead-letter requirement. A malicious or accidental render that produces a multi-GB PNG will consume storage and bandwidth with no guard.

**Scope if implementing**: A `_render_with_byte_cap` wrapper around the MCP tool call, or a response-reading middleware in `get_puppeteer_tools`. Wire `PUPPETEER_MAX_RENDER_BYTES=2097152` as a module constant. Update tests. Likely touches `app/core/puppeteer_mcp.py` only.

### C2 — `verify_attachment_token` Dead Code: CONFIRMED

**Dead code confirmed.** The function `app/core/attachment_tokens.py:91-125` is:
- Exported in `__all__` ✓
- Imported at `app/api/attachments.py:22` ✓
- **Never called** — the route re-implements verification inline at `attachments.py:66-96`

Inline re-implementation details:
- `attachments.py:71`: `max_age=300` is hardcoded — should use `DEFAULT_TTL_SECONDS`
- `attachments.py:66-96`: duplicates `_derive_key`, `_SALT`, `URLSafeTimedSerializer` construction — these private symbols are imported directly from `attachment_tokens`

**Test risk**: `tests/api/test_attachments.py` calls the route (not the helper), so no test directly pins `verify_attachment_token`'s current boolean-only return. Safe to refactor.

**Scope if implementing**: Change `verify_attachment_token` signature to return `(bool, str | None)` — the route calls the helper and uses its TTL constant. Refactor `attachments.py` to call the helper. Low risk.

### C3 — DoS via Un-paginated Query: CONFIRMED

**Query at `attachments.py:105-108`**:
```python
rows: list[Message] = (
    db.query(Message)
    .filter(Message.user_id == user_id)
    .all()
)
```
Loads **all** messages for a user, then filters attachments in Python. With multiple diagrams per chat and multi-turn sessions, this scales poorly.

**No JSONB index exists on `messages.attachments`**. Search:
```
rg -rn "attachments.*GIN|gin.*attachments|idx_messages_attachments" migrations/
→ ZERO matches
```
The `0012_add_document_chunks_indexes.sql` is the GIN index precedent (`ivfflat` for embeddings), but there is no equivalent for `messages.attachments`.

**Scope if implementing**: New migration `0015_add_message_attachments_gin.sql` with `CREATE INDEX IF NOT EXISTS idx_messages_attachments_id ON messages USING gin (attachments jsonb_path_ops)`. Python fallback in `attachments.py` for SQLite (tests). Touches `migrations/`, `schema.sql`, `app/api/attachments.py`.

---

## 2. Additional Findings

### A. `_RATE_LIMIT_LOCK` Declared but Never Used

`puppeteer_mcp.py:76`:
```python
_RATE_LIMIT_LOCK = None  # lazily created; see ``_check_rate_limit``
```
`_check_rate_limit` at lines 98-136 has **no locking whatsoever**. The comment references `_RATE_LIMIT_LOCK` but the variable is never checked or used. This is a **race condition** in multi-worker deployments (uvicorn with `workers > 1`). The `_RATE_LIMITER` dict is mutated without synchronization.

**In practice**: If the backend runs as a single uvicorn process (default in docker-compose), the asyncio event loop is single-threaded and the rate limiter behaves correctly between coroutines. However, gunicorn or multiple uvicorn workers would race. This is a latent issue; the design doc already flags "single-replica only" as an assumption.

**Decision**: Fix or defer. Fixing requires wrapping `_check_rate_limit` with `asyncio.Lock()`. The lock is cheap and removes the latent bug without changing any behavior.

### B. `PUPPETEER_MAX_RENDER_BYTES` Constant Absent

The design doc §2.2 lists it in the env var table, but the Python constant is never defined. Any implementation needs to add:
```python
_MAX_RENDER_BYTES: int = 2097152  # 2 MB
```
to `puppeteer_mcp.py` alongside `_FETCH_TIMEOUT_SECONDS`.

### C. No GIN Index Migration for `messages.attachments`

The `0012_add_document_chunks_indexes.sql` is the precedent for adding indexes via migration. A new `0015_add_message_attachments_gin.sql` is needed for C3. `schema.sql` also needs the index mirrored.

### D. Rate Limiter Test Uses `monkeypatch.setenv` — Parallel Test Risk

`test_puppeteer_mcp.py:214-226` (`test_rate_limit_allows_5_calls_in_60s`) uses `monkeypatch.setenv("PUPPETEER_RENDER_RATE_LIMIT_PER_MINUTE", "5")` but the autouse `reset_puppeteer_state` fixture resets the rate limiter between tests. No isolation issue in practice, but the test modifies global process state.

---

## 3. Implementation Constraints

### Wrapper Pattern — Similar to `context7_mcp.py`

`context7_mcp.py` has no byte cap and no rate limiter — it is simpler. The `puppeteer_mcp.py` pattern is the reference. For byte cap:
- Add `_MAX_RENDER_BYTES` constant
- The cap must be applied at the tool **call result** level (after `client.get_tools()` returns), not on the `get_tools` fetch itself — the timeout is on the tool metadata fetch, the byte cap is on the render result.
- `puppeteer_screenshot` returns base64-encoded PNG. The byte cap check needs to decode and measure, or check the raw response size before decoding.
- Alternative: add a `max_bytes` parameter to `get_puppeteer_tools` and wrap the tool result, but that changes the call shape in `agent.py`.

**Recommended approach**: Add `_MAX_RENDER_BYTES` constant + a `_check_render_size(result)` guard in `get_puppeteer_tools`. The MCP tool result from `puppeteer_screenshot` is a dict with a `data` (base64) or `dataUrl` field. Check `len(data)` after base64 decoding. Raise `PuppeteerUnavailable(reason="puppeteer_byte_cap")` if over limit.

### Test Structure

| File | Pattern |
|---|---|
| `tests/core/test_puppeteer_mcp.py` | Unit tests for module-level helpers; mock `MultiServerMCPClient` |
| `tests/core/test_attachment_tokens.py` | Unit tests for token helpers; mock-free (uses `itsdangerous`) |
| `tests/api/test_attachments.py` | Integration tests with SQLite in-memory; patch `SessionLocal` |

The `conftest.py` has an autouse `reset_puppeteer_state` fixture that calls `puppeteer_mcp.reset_client_for_tests()` — this handles singleton + rate limiter cleanup between tests. The `test_attachment_tokens.py` uses `reset_serializer_for_tests()`.

### Test for Byte Cap

A new test in `test_puppeteer_mcp.py`:
```python
def test_byte_cap_raises_when_render_exceeds_2mb(monkeypatch):
    # Mock a tool result > 2MB and verify PuppeteerUnavailable(reason="puppeteer_byte_cap")
```

---

## 4. Scope Expansion Risk for C3 (JSONB GIN)

**Files that would change for C3**:

| File | Change |
|---|---|
| `migrations/0015_add_message_attachments_gin.sql` (NEW) | `CREATE INDEX IF NOT EXISTS idx_messages_attachments_id ON messages USING gin (attachments jsonb_path_ops)` |
| `schema.sql` | Mirror the index after `ALTER TABLE messages ADD COLUMN IF NOT EXISTS attachments` |
| `app/api/attachments.py` | Replace Python-filter loop with `db.query(Message).filter(Message.user_id == user_id, Message.attachments.contains([{"id": id}])).first()` for Postgres; keep Python filter for SQLite |
| `tests/api/test_attachments.py` | SQLite JSONB patch already in place — existing tests cover the route; add a performance-oriented test with many messages if desired |

The `0012_add_document_chunks_indexes.sql` precedent shows the migration naming and idempotent index pattern. The GIN index uses `jsonb_path_ops` (not `jsonb_ops`) for efficient `@>` containment queries on array elements.

**Risk**: Changing the query from "load all + filter in Python" to "filter in SQL" changes the SQL generated. The SQLite fallback in tests doesn't support `@>` — the existing Python-filter approach must remain for test compatibility.

---

## 5. First-Slice Scope Recommendation

**Minimum viable fix for the 3 critical findings**:

| Finding | Fix | Files |
|---|---|---|
| C1 (byte cap) | Add `_MAX_RENDER_BYTES = 2097152` constant; add size guard in `get_puppeteer_tools`; raise `PuppeteerUnavailable(reason="puppeteer_byte_cap")` | `app/core/puppeteer_mcp.py`, `tests/core/test_puppeteer_mcp.py` |
| C2 (dead code) | Refactor `attachments.py` route to call `verify_attachment_token`; use `DEFAULT_TTL_SECONDS`; drop inline duplicate | `app/api/attachments.py`, `app/core/attachment_tokens.py` |
| C3 (DoS query) | Add GIN index migration; switch to `contains()` query for Postgres; Python fallback for SQLite | `migrations/0015_*.sql`, `schema.sql`, `app/api/attachments.py` |

**Optional additions for the same PR**:
- Fix the `_RATE_LIMIT_LOCK` race condition (add `asyncio.Lock()`)
- Update `verify-report.md` to correct the false "byte cap wired" claim

**Out of scope for this PR**:
- Any F14 items (multi-turn memory, HTML sanitizer, Redis rate limiter)
- Frontend changes (F13 frontend is already in PR #76)

---

## 6. Risks

| Risk | Severity | Notes |
|---|---|---|
| Byte cap implementation choice (where to apply the check) | MEDIUM | Must be on tool call result, not `get_tools` metadata fetch |
| `attachments.contains()` not supported in SQLite test DB | MEDIUM | Must retain Python-filter fallback for tests |
| Changing `verify_attachment_token` signature | LOW | No tests pin the current boolean-only return; route refactor is mechanical |
| Rate limiter race if backend runs multi-worker | LOW | Fix is a one-line `asyncio.Lock()` wrapper — cheap |
| Migration numbering conflict | LOW | `0013` is the next available; `0014` is taken by `proposal_approvals` |

---

## 7. References

- Spec: `openspec/specs/puppeteer-mcp-integration/spec.md` (REQ-PMCP-3)
- Spec: `openspec/specs/chat-attachments/spec.md` (REQ-ATT-2)
- Design: `openspec/changes/2026-09-07-F13-puppeteer-mcp/design.md`
- Verify: `openspec/changes/2026-09-07-F13-puppeteer-mcp/verify-report.md` (claim at §3 that byte cap is "wired" is incorrect)
- Migration precedent: `migrations/0012_add_document_chunks_indexes.sql`
- Test fixtures: `tests/conftest.py` (`reset_puppeteer_state` autouse)
- Test attachments: `tests/api/test_attachments.py` (SQLite JSONB patch at top)
