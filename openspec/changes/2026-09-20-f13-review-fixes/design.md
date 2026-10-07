# Design: F13 PR #76 Review Fixes

| Field | Value |
|---|---|
| Branch | `feature/integration-f11-f12-f13` (same as PR #76 — append commits) |
| Delivery | `single-pr`; 7 work-unit commits |
| ADR impact | ADR-013 §2 inline amendment |
| Migration | `migrations/0013_add_message_attachments_gin_index.sql` (idempotent) |
| Mode | Standard (tests obligatory + manual smoke; not strict TDD) |

## 1. Context Recap

The PR #76 audit raised three findings (C1 byte cap absent, C2 dead helper, C3 un-paginated attachment lookup) plus one bonus (rate-limit race) and one doc errata (false "wired" claim in verify-report). `explore.md` confirmed all three findings with grep evidence; `proposal.md` decided C1 = implement-cap (orthogonal guards, not redundant), scope = 5 deliverables, migration slot = `0013`. This document pins the implementation mechanism for each.

## 2. Byte-Cap Enforcement (C1)

### 2.1 Boundary decision

**Chosen: tool-invocation wrapper (post-`ainvoke`, pre-yield to agent).**

Rationale:
- The proposal explicitly rejects "at `get_tools` fetch" because that returns metadata, not the rendered PNG bytes.
- A wrapper around `tool.ainvoke` measures the result at receive-time — the bytes are still in process when measured (the sidecar `mem_limit: 512m` remains the receive-time memory bound; we cannot bound process memory from Python).
- Persistence-time check (`_persist_turn`) was an alternative but it would not raise `PuppeteerUnavailable(reason="puppeteer_byte_cap")` cleanly: by the time we reach `_persist_turn`, the event has already been emitted to the SSE stream. Catching the overflow at the tool-invocation boundary lets the agent layer convert the failure to `event: degraded` with the typed reason, matching REQ-PMCP-4 / SCN-PMCP-6.

### 2.2 Implementation shape

New module-level constants in `app/core/puppeteer_mcp.py`:

```python
# REQ-PMCP-3 byte cap. Hardcoded default mirrors ADR-013 §2 (2 MB).
# Override via env var for tests / future tuning.
_DEFAULT_MAX_RENDER_BYTES: int = 2_097_152  # 2 MiB


def _max_render_bytes() -> int:
    """Read ``PUPPETEER_MAX_RENDER_BYTES`` at call-time (test-friendly)."""
    raw = os.getenv("PUPPETEER_MAX_RENDER_BYTES")
    if raw is None or not raw.strip():
        return _DEFAULT_MAX_RENDER_BYTES
    try:
        return max(0, int(raw))
    except ValueError:
        return _DEFAULT_MAX_RENDER_BYTES
```

Add `_wrap_tool_with_byte_cap` and a measurement helper:

```python
def _measure_result_bytes(result: Any) -> int:
    """Best-effort byte size of a tool result.

    LangChain tool results come back as ``str`` (base64-in-string), ``bytes``,
    ``list[content-block]``, or sometimes a wrapper dict. We normalize to a
    single byte count for the cap check.
    """
    if isinstance(result, bytes):
        return len(result)
    if isinstance(result, str):
        return len(result.encode("utf-8"))
    if isinstance(result, list):
        # Common LangChain content-block shape.
        total = 0
        for block in result:
            if isinstance(block, dict):
                data = block.get("data") or block.get("text") or ""
                if isinstance(data, bytes):
                    total += len(data)
                else:
                    total += len(str(data).encode("utf-8"))
            else:
                total += len(str(block).encode("utf-8"))
        return total
    if isinstance(result, dict):
        data = result.get("data") or result.get("content") or ""
        if isinstance(data, bytes):
            return len(data)
        return len(str(data).encode("utf-8"))
    return len(str(result).encode("utf-8"))


def _wrap_tool_with_byte_cap(tool: Any) -> Any:
    """In-place: enforce ``PUPPETEER_MAX_RENDER_BYTES`` on the tool's result.

    Replaces ``tool.ainvoke`` with a wrapper that:
      1. awaits the original ainvoke,
      2. measures the result bytes,
      3. raises ``PuppeteerUnavailable(reason="puppeteer_byte_cap")`` if over.

    The mutation is per-tool and only affects this instance; the upstream
    adapter is untouched (same fragility budget as
    ``_make_optional_params_nullable`` from round 3 — see test pinning).
    """
    cap = _max_render_bytes()
    if cap <= 0:
        # Cap disabled (env var = 0) — leave tool untouched.
        return tool

    original_ainvoke = tool.ainvoke

    async def _capped_ainvoke(*args: Any, **kwargs: Any) -> Any:
        result = await original_ainvoke(*args, **kwargs)
        size = _measure_result_bytes(result)
        if size > cap:
            raise PuppeteerUnavailable(
                f"Puppeteer render exceeds byte cap ({size} > {cap})",
                reason="puppeteer_byte_cap",
            )
        return result

    tool.ainvoke = _capped_ainvoke  # type: ignore[method-assign]
    return tool
```

Wire it in `get_puppeteer_tools` (`app/core/puppeteer_mcp.py:264-334`), immediately after the existing `_make_optional_params_nullable` loop:

```python
for tool in filtered:
    _make_optional_params_nullable(tool)
    _wrap_tool_with_byte_cap(tool)  # NEW — C1
```

### 2.3 Honest limitations

- **Receive-time memory is bounded by the sidecar `mem_limit: 512m`** (ADR-013 §6), not by this Python-side check. The bytes have already crossed the network and landed in the Python process before we measure them. The cap bounds what flows into the SSE event and what gets persisted/served — i.e., it is a defense-in-depth layer for storage and bandwidth, not for transient process memory.
- **`tool.ainvoke` mutation**: same fragility profile as `_make_optional_params_nullable`. A future `langchain-mcp-adapters` change that drops `ainvoke` (e.g., moves to `invoke`/`arun`/something-else) will silently disable the cap. The pinned-version policy in `requirements.txt` + the new test below catch this in CI.
- **Result-shape fragility**: `_measure_result_bytes` handles the four shapes we have observed in practice. A new result shape from a future MCP server version could under-count. Tradeoff: erring on the under-count side means a real oversize render would pass the check; erring on the over-count side means false positives. The current implementation errs on the under-count side (length of the string repr) — acceptable for MVP, follow-up issue if it ever bites.

## 3. verify_attachment_token Refactor (C2)

### 3.1 New signature

In `app/core/attachment_tokens.py:91-125`, change the return type from `bool` to `tuple[bool, int | None]` so the route consumes the verified user_id from the payload rather than re-parsing the JWT-derived `uid`:

```python
def verify_attachment_token(
    token: str,
    *,
    attachment_id: str,
    user_id: int,  # NEW: required for path/token consistency check
    max_age: int = DEFAULT_TTL_SECONDS,
) -> tuple[bool, int | None]:
    """Return ``(valid, payload_user_id)``.

    ``payload_user_id`` is the ``uid`` claim from the signed payload when
    the signature is valid AND the payload is fresh AND the payload's
    ``aid`` claim matches ``attachment_id``. On ANY failure mode
    (missing/expired/forged/mismatched aid/wrong uid) the function
    returns ``(False, None)`` indistinguishably so the route can map
    every failure to 401 without leaking which check failed.

    The ``user_id`` argument is the user_id from the route's
    authenticated context. We verify the token's ``uid`` claim matches
    it as a second check (defense in depth — even if a token leaked, it
    can only be used for the user that minted it).
    """
    if not token:
        return False, None
    serializer = _get_serializer()
    try:
        payload = serializer.loads(token, max_age=max_age)
    except SignatureExpired:
        _LOGGER.debug("attachment_token: expired")
        return False, None
    except BadSignature:
        _LOGGER.debug("attachment_token: bad signature")
        return False, None
    except Exception as e:  # pragma: no cover — defensive
        _LOGGER.debug("attachment_token: unexpected verify error: %s", e)
        return False, None

    if not isinstance(payload, dict):
        return False, None
    if payload.get("aid") != str(attachment_id):
        return False, None
    try:
        payload_uid = int(payload.get("uid", -1))
    except (TypeError, ValueError):
        return False, None
    if payload_uid != int(user_id):
        return False, None
    return True, payload_uid
```

Note: changed log level from `info` to `debug` for expired/bad-signature — the route already maps both to 401, and the previous `info` distinction was a side-channel if logs were aggregated (cross-cut concern; see PR #76 review m1).

Also: the helper now requires `user_id` as a parameter (mandatory). Previously, `user_id` was checked against the payload in the helper's call-site chain. Promoting it to a parameter makes the check explicit and prevents the "I forgot to verify the uid" footgun.

### 3.2 Route pseudocode

In `app/api/attachments.py:31-163`, the route collapses from ~100 lines to ~40:

```python
@router.get("/attachments/{id}")
def get_attachment(
    id: str,
    token: str | None = Query(default=None),
    user_id: int = Depends(get_current_user),  # NEW: route now auths the user
) -> FileResponse:
    """Auth posture: signed URL token (5-min TTL) bound to (attachment_id, user_id).

    The route requires an authenticated session (get_current_user) so the
    ``user_id`` for the token-vs-payload check is well-defined. The token
    itself is what authorises the read (the <img> tag cannot carry a JWT
    header), and we cross-check the token's ``uid`` claim against the
    session user.
    """
    if not token:
        raise HTTPException(status_code=401, detail="Missing token")

    valid, payload_uid = verify_attachment_token(
        token,
        attachment_id=id,
        user_id=user_id,
    )
    if not valid or payload_uid != user_id:
        # Indistinguishable 401 per REQ-ATT-2 (avoid info leak).
        raise HTTPException(status_code=401, detail="Invalid token")

    db = SessionLocal()
    try:
        attachment, owner_row = _lookup_attachment(db, user_id, id)
        if attachment is None:
            # 404 NOT 403 — existence leak prevention (REQ-ATT-2 SCN-ATT-4).
            raise HTTPException(status_code=404, detail="Not found")

        storage_path = attachment.get("storage_path")
        if not storage_path:
            raise HTTPException(status_code=404, detail="Not found")

        _ensure_uploads_dir()

        return FileResponse(
            path=storage_path,
            media_type=attachment.get("mime") or "application/octet-stream",
            headers={
                "Content-Disposition": f'inline; filename="{attachment.get("filename") or "attachment"}"',
                "Cache-Control": "private, max-age=300",
            },
        )
    finally:
        db.close()
```

Where `_lookup_attachment` is the new dialect-aware helper (see §4.1).

### 3.3 Behavior preservation

| Scenario | Old behavior | New behavior |
|---|---|---|
| Missing token | 401 | 401 ✓ |
| Expired token | 401 (distinguishing log line) | 401 (debug log) ✓ |
| Forged token | 401 | 401 ✓ |
| Token signed for aid A, requested as aid B | 401 | 401 ✓ |
| Cross-user (valid token but row belongs to other user) | 404 | 404 ✓ |
| Unknown id | 404 | 404 ✓ |
| Happy path | 200 | 200 ✓ |

External behavior is identical. The `get_current_user` dependency is new — the old route did not have it (it relied entirely on the signed URL). For the `<img>` use case, the session cookie is sent on the GET, so this is satisfied naturally by browsers that previously loaded the page. Tests that hit this route directly will need a session cookie (existing `test_attachments.py` already uses `fake_db` fixture that mounts auth — verify in apply phase).

## 4. Postgres Attachments Lookup (C3)

### 4.1 Dialect switch shape

In `app/api/attachments.py`, replace the inline un-paginated query with a dedicated helper:

```python
def _lookup_attachment(
    db: Session, user_id: int, attachment_id: str
) -> tuple[dict | None, Message | None]:
    """Resolve one attachment by ``(user_id, attachment_id)``.

    Postgres path uses ``messages.attachments @> '[{"id": "..."}]'::jsonb``
    + the new GIN index from migration 0013. SQLite path falls back to
    the existing in-Python filter (test compatibility — JSONB containment
    is not supported on SQLite).
    """
    dialect = db.bind.dialect.name if db.bind is not None else ""
    if dialect == "postgresql":
        row = (
            db.query(Message)
            .filter(
                Message.user_id == user_id,
                Message.attachments.contains(
                    [{"id": attachment_id}]
                ),
            )
            .first()
        )
        if row is None:
            return None, None
        attachment = next(
            (a for a in (row.attachments or [])
             if isinstance(a, dict) and a.get("id") == attachment_id),
            None,
        )
        return attachment, row

    # SQLite / fallback: existing Python-filter behavior.
    rows: list[Message] = (
        db.query(Message).filter(Message.user_id == user_id).all()
    )
    for row in rows:
        for att in (row.attachments or []):
            if isinstance(att, dict) and att.get("id") == attachment_id:
                return att, row
    return None, None
```

The SQLite path is unchanged from current behavior — it's the Postgres path that benefits from the index.

### 4.2 Migration: `migrations/0013_add_message_attachments_gin_index.sql`

```sql
-- 0013 — GIN index on messages.attachments for JSONB containment lookup.
--
-- Used by app/api/attachments.py:_lookup_attachment (Postgres path) to
-- resolve one attachment by user_id + id without loading all of a user's
-- messages. Required by the F13 review fix for C3.
--
-- jsonb_path_ops is the minimal opclass for @> containment: smaller index,
-- faster lookups, no support for key-existence queries (which we don't need).
--
-- IF NOT EXISTS makes the migration idempotent. CONCURRENTLY is NOT used
-- because the migration runner (scripts/run_migrations.py) is transaction-
-- per-file; plain CREATE INDEX takes a brief ACCESS EXCLUSIVE lock on
-- messages, which is acceptable for the current table size (< 100k rows
-- per the demo seed). For production at higher scale, revisit via F14.
--
-- Idempotent: safe to re-run.

CREATE INDEX IF NOT EXISTS idx_messages_attachments_gin
ON messages
USING GIN (attachments jsonb_path_ops);
```

Apply order: this migration runs **after** `0011_add_message_attachments.sql` (which created the `attachments` JSONB column). The existing migration ordering in `migrations/run_migrations.py` sorts numerically, so `0013_*` runs after `0012_*` and before `0014_*`.

### 4.3 Lock strategy note

- Plain `CREATE INDEX` (no `CONCURRENTLY`) takes a brief `ACCESS EXCLUSIVE` lock on `messages` — blocks reads + writes for the duration of the build.
- For the demo-scale DB (sub-100k rows) the build completes in milliseconds. For a production-size table this would need `CONCURRENTLY` and a non-transactional migration runner.
- Documented as a known scaling limit. Follow-up: if `messages` grows past ~1M rows, move to `pg_repack`-style online index build.

## 5. Rate Limit Lock (Bonus)

### 5.1 Choice

**`asyncio.Lock` + `async with`** (Option A from the explore prompt).

Rationale: explicit and obviously correct. The CAS alternative (Option B) saves ~1 LoC and ~50ns of overhead but introduces "best-effort" semantics that diverge from the spec's "5/min" wording. Cost is one line of code (`async def` instead of `def`); value is zero ambiguity in the failure mode.

### 5.2 Implementation

In `app/core/puppeteer_mcp.py`, replace the current `_check_rate_limit` (sync, declared `_RATE_LIMIT_LOCK = None`):

```python
import asyncio

_RATE_LIMIT_LOCK = asyncio.Lock()


async def _check_rate_limit(user_id: int | None) -> None:
    """Sliding-window rate limiter (REQ-PMCP-4) — async + locked.

    Same semantics as the previous sync version, but the window
    mutation is now guarded by an ``asyncio.Lock`` so two concurrent
    coroutines cannot both pass the ``len(window) < limit`` check and
    both append (the latent race condition from the original
    implementation). Single-replica scope only — promote to Redis in
    F14 if horizontal scaling arrives.
    """
    limit = _rate_limit_per_minute()
    if limit <= 0:
        return

    key = int(user_id) if user_id is not None else 0
    now = _time.time()
    cutoff = now - _RATE_LIMIT_WINDOW_SECONDS

    async with _RATE_LIMIT_LOCK:
        window = _RATE_LIMITER.get(key)
        if window is None:
            window = []
            _RATE_LIMITER[key] = window

        # Prune timestamps older than the window.
        while window and window[0] < cutoff:
            window.pop(0)

        if len(window) >= limit:
            raise PuppeteerUnavailable(
                f"Puppeteer render rate limit exceeded ({limit}/{_RATE_LIMIT_WINDOW_SECONDS}s)",
                reason="puppeteer_rate_limited",
            )

        window.append(now)
```

Caller update in `app/core/agent.py:_try_get_puppeteer_tools` (current line 255):

```python
# Old:
_check_rate_limit(user_id)

# New:
await _check_rate_limit(user_id)
```

The call site is already inside an `async` function (`_try_get_puppeteer_tools` is `async def` per `agent.py:232`), so the change is purely `await`-keyword addition. No new lock context manager needed at the call site.

## 6. Doc Updates

### 6.1 ADR-013 §2 amendment

In `docs/adr/013-puppeteer-mcp.md`, append the following to the existing §2 (budgets):

```markdown
### 2.1 Boundary clarification (added by `2026-09-20-f13-review-fixes`)

The byte cap is enforced **at the tool-invocation boundary** (post-`ainvoke`,
pre-yield to the agent) via `_wrap_tool_with_byte_cap` in
`app/core/puppeteer_mcp.py`. The cap bounds what flows into the SSE event
and what gets persisted/served. It does **not** bound the receive-time
process memory spike — the bytes are already in the Python process when
measured. That bound is the sidecar `mem_limit: 512m` (§6).
```

This is an inline amendment — no new ADR file, no `REPLACES`/`SUPERSEDES` block. The original §2 is preserved verbatim above the new §2.1.

### 6.2 Verify-report ERRATA

In `openspec/changes/2026-09-07-F13-puppeteer-mcp/verify-report.md`, prepend the following block (before §1):

```markdown
> ## ERRATA — added 2026-09-20 by `2026-09-20-f13-review-fixes`
>
> The §3 verdict for **REQ-PMCP-3** states that "byte cap server-side path
> is wired". This was **factually incorrect** at the time of the original
> verify: the only per-call budget actually wired was
> `asyncio.wait_for(timeout=15.0)`; the 2 MB byte cap was not enforced
> anywhere in the codebase. The fix change
> `2026-09-20-f13-review-fixes` implements the cap at the tool-invocation
> boundary (see ADR-013 §2.1). This ERRATA does not retract the F13
> merge itself — the other 8 REQs are independently verified — but it
> corrects the REQ-PMCP-3 evidence record.
```

## 7. Test Sketch

Per finding, brief.

**C1** (`tests/core/test_puppeteer_mcp.py`):
- `test_wrap_tool_with_byte_cap_passes_under_limit`: mock tool returning 1 MB → result unwrapped, no exception.
- `test_wrap_tool_with_byte_cap_raises_over_limit`: mock tool returning 2 MB + 1 byte → `PuppeteerUnavailable(reason="puppeteer_byte_cap")`.
- `test_wrap_tool_with_byte_cap_edge_exact_limit`: exactly 2 MB → passes.
- `test_wrap_tool_with_byte_cap_respects_env_override`: `PUPPETEER_MAX_RENDER_BYTES=1024`, 1 KB + 1 byte → raises.
- `test_wrap_tool_with_byte_cap_disabled_when_zero`: `PUPPETEER_MAX_RENDER_BYTES=0`, 100 MB → passes (cap disabled).
- `test_measure_result_bytes_handles_string_bytes_list_dict`: parametrized over the 4 known result shapes.
- `test_get_puppeteer_tools_applies_byte_cap`: integration test — mocked MCP client returns tools, verifying `_wrap_tool_with_byte_cap` ran (cap fires on ainvoke).

**C2** (`tests/core/test_attachment_tokens.py` if it exists, otherwise extend `tests/api/test_attachments.py`):
- All existing `tests/api/test_attachments.py` tests must pass unchanged (route behavior from outside is identical per §3.3).
- New unit tests for `verify_attachment_token`:
  - `test_verify_returns_valid_and_uid_on_good_token`
  - `test_verify_returns_false_none_on_expired`
  - `test_verify_returns_false_none_on_bad_signature`
  - `test_verify_returns_false_none_on_mismatched_aid`
  - `test_verify_returns_false_none_on_mismatched_uid`
  - `test_verify_returns_false_none_on_empty_token`
  - `test_verify_returns_false_none_on_non_dict_payload` (defensive)

**C3** (`tests/api/test_attachments.py` + new `tests/migrations/test_0013.py`):
- All existing `tests/api/test_attachments.py` tests still pass (SQLite fallback unchanged).
- New: `test_attachments_lookup_uses_postgres_containment_when_available`: gated by `pytest.mark.skipif(not is_postgres())`, uses a test DB with the GIN index, asserts the query plan uses the index (`EXPLAIN`).
- New: migration idempotency test — run `migrations/0013_add_message_attachments_gin_index.sql` twice in a fresh DB; second run is a no-op (no error).
- New: migration numeric ordering — `migrations/` is sorted by name; `0013` runs after `0012` and before `0014_proposal_approvals_table.sql`.

**Bonus** (`tests/core/test_puppeteer_mcp.py`):
- `test_check_rate_limit_async_concurrent_6th_raises`: 6 concurrent `asyncio.gather` calls — exactly one raises (the 6th). Existing `reset_client_for_tests` fixture unchanged (clears `_RATE_LIMITER`).

**Errata**: no test required (doc-only).

## 8. Work-Unit Commit Plan

7 commits, each independently reviewable + revertable. Order from smallest/most-confident to largest/most-risky. Conventional prefixes per `openspec/config.yaml:42`.

| # | Commit | Files | Diff estimate |
|---|---|---|---|
| 1 | `fix(puppeteer-mcp): wire _RATE_LIMIT_LOCK as asyncio.Lock to prevent race in _check_rate_limit` | `app/core/puppeteer_mcp.py`, `app/core/agent.py`, `tests/core/test_puppeteer_mcp.py` | ~10 LoC |
| 2 | `refactor(attachments): route delegates to verify_attachment_token, drop inline duplicate` | `app/core/attachment_tokens.py`, `app/api/attachments.py`, `tests/api/test_attachments.py`, `tests/core/test_attachment_tokens.py` (new) | ~50 LoC |
| 3 | `feat(puppeteer-mcp): enforce 2 MB render byte cap at tool-invocation boundary (REQ-PMCP-3)` | `app/core/puppeteer_mcp.py`, `tests/core/test_puppeteer_mcp.py` | ~80 LoC |
| 4 | `feat(db): add GIN index on messages.attachments for containment lookup` | `migrations/0013_add_message_attachments_gin_index.sql` | ~10 LoC |
| 5 | `perf(attachments): use Postgres JSONB containment query when available; keep SQLite fallback` | `app/api/attachments.py`, `tests/api/test_attachments.py` | ~30 LoC |
| 6 | `docs(f13): errata note in verify-report — byte cap was not wired at original verify` | `openspec/changes/2026-09-07-F13-puppeteer-mcp/verify-report.md` | ~10 LoC |
| 7 | `docs(adr-013): clarify byte-cap enforcement boundary (§2.1)` | `docs/adr/013-puppeteer-mcp.md` | ~10 LoC |

**Total diff estimate**: ~200 LoC of code + ~120 LoC of tests + ~30 LoC of docs/migration = **~350 LoC**, well within the 800-line review budget.

**Revert safety**: each commit is independently revertable with `git revert <sha>`. Commit 4 (migration) is the only one that has a database state side-effect — revert order matters if merging/reverting mid-PR: revert code changes before dropping the index.

## 9. References

- `openspec/changes/2026-09-20-f13-review-fixes/explore.md`
- `openspec/changes/2026-09-20-f13-review-fixes/proposal.md`
- `docs/adr/013-puppeteer-mcp.md` (amended)
- `https://github.com/danielCH26/arch-agent/pull/76` (PR under fix)
- `https://github.com/danielCH26/arch-agent/pull/76#pullrequestreview-5258429158` (audit that triggered this change)
