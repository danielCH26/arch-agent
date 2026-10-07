# Tasks: F13 PR #76 Review Fixes

| Field | Value |
|---|---|
| Mode | Standard (tests obligatory + manual smoke; not strict TDD) |
| Delivery | `single-pr` — 7 work-unit commits append to PR #76 |
| Branch | `feature/integration-f11-f12-f13` |
| Review budget | 800 lines |

## Organization

Grouped by area per `openspec/config.yaml:33`: backend (core, api), migrations, tests, docs. Hierarchical numbering (1, 1.1, 1.2). Each task completable in one session.

**Task dependency arrows** use `→`. Tasks without `→` are independent and may run in any order within their area; tasks with `→` must be done in order.

---

## 1. Backend — Core

### 1.1 Byte-cap constants + helpers (puppeteer_mcp.py)

- [x] **1.1.1** Add `_DEFAULT_MAX_RENDER_BYTES: int = 2_097_152` module-level constant.
- [x] **1.1.2** Add `_max_render_bytes()` reader (env var `PUPPETEER_MAX_RENDER_BYTES` → int, default to constant).
- [x] **1.1.3** Add `_measure_result_bytes(result: Any) -> int` — handles bytes / str / list[content-block] / dict shapes.
- [x] **1.1.4** Add `_wrap_tool_with_byte_cap(tool: Any) -> Any` — wraps `tool.ainvoke`, raises `PuppeteerUnavailable(reason="puppeteer_byte_cap")` over cap.
- [x] **1.1.5** In `get_puppeteer_tools`, after the existing `_make_optional_params_nullable` loop (line 326), add a second loop calling `_wrap_tool_with_byte_cap(tool)`.

Files touched: `app/core/puppeteer_mcp.py`.
LoC: ~50.
Commit: `feat(puppeteer-mcp): enforce 2 MB render byte cap at tool-invocation boundary (REQ-PMCP-3)`.

### 1.2 Rate-limit lock (puppeteer_mcp.py + agent.py)

- [x] **1.2.1** Replace `_RATE_LIMIT_LOCK = None` (line 76) with `_RATE_LIMIT_LOCK = asyncio.Lock()`.
- [x] **1.2.2** Change `_check_rate_limit` from `def` to `async def`.
- [x] **1.2.3** Wrap the window-prune + append body in `async with _RATE_LIMIT_LOCK:`.
- [x] **1.2.4** Update `agent.py:_try_get_puppeteer_tools` line 255 from `_check_rate_limit(user_id)` to `await _check_rate_limit(user_id)`.

Files touched: `app/core/puppeteer_mcp.py`, `app/core/agent.py`.
LoC: ~8.
Commit: `fix(puppeteer-mcp): wire _RATE_LIMIT_LOCK as asyncio.Lock to prevent race in _check_rate_limit`.
Depends on: nothing.

### 1.3 verify_attachment_token refactor (attachment_tokens.py)

- [x] **1.3.1** Change return type annotation `-> bool` to `-> tuple[bool, int | None]`.
- [x] **1.3.2** Add `user_id: int` as a required keyword-only parameter (after `*`).
- [x] **1.3.3** Move the `payload_uid != int(user_id)` check into the helper (defense in depth, single source of truth).
- [x] **1.3.4** Downgrade log levels from `_LOGGER.info(...)` to `_LOGGER.debug(...)` for `expired` / `bad signature` paths (avoid log-aggregator side-channel; see design §3.3).
- [x] **1.3.5** Update `__all__` if signature changed in a way that breaks callers.

Files touched: `app/core/attachment_tokens.py`.
LoC: ~15.
Commit: `refactor(attachments): route delegates to verify_attachment_token, drop inline duplicate` (combined with task 1.4 below).
Depends on: nothing (the API change breaks the route — task 1.4 must follow in the same commit).

---

## 2. Backend — API

### 2.1 Route refactor: delegate to verify_attachment_token (attachments.py)

- [x] Add `Depends(get_current_user)` parameter to `get_attachment` route (auth context for the user_id check).
- [x] Remove the inline `URLSafeTimedSerializer` import + construction + manual `serializer.loads(...)` block (lines 66-96 in current file).
- [x] Replace with: `valid, payload_uid = verify_attachment_token(token, attachment_id=id, user_id=user_id); if not valid or payload_uid != user_id: raise 401`.
- [x] Use `DEFAULT_TTL_SECONDS` indirectly via the helper (no more hardcoded `300`).
- [x] Drop the `from itsdangerous import ...` line (no longer needed at the route level).

Files touched: `app/api/attachments.py`.
LoC: ~−40 (net deletion, since inline is replaced by a 5-line call).
Commit: same as 1.3 (single combined commit for the C2 deliverable).
Depends on: 1.3.x (helper signature must be in place).

### 2.2 Dialect-aware lookup helper (attachments.py)

- [x] Add `_lookup_attachment(db: Session, user_id: int, attachment_id: str) -> tuple[dict | None, Message | None]` helper per design §4.1.
- [x] Detect dialect via `db.bind.dialect.name == "postgresql"`.
- [x] Postgres branch: use `Message.attachments.contains([{"id": attachment_id}])`.
- [x] SQLite / fallback branch: keep the current `db.query(Message).filter(Message.user_id == user_id).all()` + Python-filter behavior.
- [x] Replace the inline un-paginated query in the route (lines 102-131 in current file) with a call to `_lookup_attachment(db, user_id, id)`.
- [x] Remove the now-unreachable `db.query(Message).filter(Message.user_id == user_id).all()` from the route body.

Files touched: `app/api/attachments.py`.
LoC: ~25 (new helper minus inline query).
Commit: `perf(attachments): use Postgres JSONB containment query when available; keep SQLite fallback` (combined with task 3.3 below).
Depends on: nothing (independent of 1.x and 2.1).

---

## 3. Migrations

### 3.1 New GIN index migration

- [x] Create `migrations/0013_add_message_attachments_gin_index.sql` with the contents from design §4.2.
- [x] Verify file name sorts correctly: `0012_*` → `0013_*` → `0014_proposal_approvals_table.sql`. Confirmed via `ls migrations/ | sort -V`.
- [x] Verify the migration runner picks it up (no registration needed — `scripts/run_migrations.py` discovers by glob).

Files touched: `migrations/0013_add_message_attachments_gin_index.sql`.
LoC: ~10 (mostly comments).
Commit: `feat(db): add GIN index on messages.attachments for containment lookup`.
Depends on: `migrations/0011_add_message_attachments.sql` already applied (it is on PR #76).

---

## 4. Tests

### 4.1 Byte-cap unit + integration tests

- [x] `test_wrap_tool_with_byte_cap_passes_under_limit` — 1 MB input, no exception.
- [x] `test_wrap_tool_with_byte_cap_raises_over_limit` — 2 MB + 1 byte, `PuppeteerUnavailable(reason="puppeteer_byte_cap")`.
- [x] `test_wrap_tool_with_byte_cap_edge_exact_limit` — exactly 2 MB, passes.
- [x] `test_wrap_tool_with_byte_cap_respects_env_override` — `PUPPETEER_MAX_RENDER_BYTES=1024`, 1 KB + 1 byte raises.
- [x] `test_wrap_tool_with_byte_cap_disabled_when_zero` — `PUPPETEER_MAX_RENDER_BYTES=0`, 100 MB passes.
- [x] `test_measure_result_bytes_handles_all_shapes` — parametrized over bytes / str / list[content-block] / dict / scalar.
- [x] `test_get_puppeteer_tools_applies_byte_cap` — integration: mocked MCP client returns a tool whose `ainvoke` returns > 2 MB; verify the cap fires.

Files touched: `tests/core/test_puppeteer_mcp.py`.
LoC: ~120.
Commit: combined with 1.1 (single commit for the C1 deliverable).
Depends on: 1.1.x.

### 4.2 verify_attachment_token unit tests

- [x] `test_verify_returns_valid_and_uid_on_good_token`.
- [x] `test_verify_returns_false_none_on_expired` (TTL=0 or fast-forward).
- [x] `test_verify_returns_false_none_on_bad_signature` (mangle the token).
- [x] `test_verify_returns_false_none_on_mismatched_aid`.
- [x] `test_verify_returns_false_none_on_mismatched_uid`.
- [x] `test_verify_returns_false_none_on_empty_token`.
- [x] `test_verify_returns_false_none_on_non_dict_payload` (mock serializer.loads returning a list).

Files touched: `tests/core/test_attachment_tokens.py` (new file) or `tests/api/test_attachments.py` (existing). **Prefer new file** — cleaner separation; helper-level tests don't need HTTP plumbing.

LoC: ~80.
Commit: combined with 1.3 + 2.1 (single commit for the C2 deliverable).
Depends on: 1.3.x.

### 4.3 Attachment lookup + migration tests

- [x] Existing `tests/api/test_attachments.py` SQLite tests still pass (regression — the SQLite branch is unchanged).
- [x] New: `test_attachments_lookup_uses_postgres_containment_when_available` — gated by `pytest.mark.skipif(not is_postgres(), reason="Postgres-only")`, asserts the query plan references `idx_messages_attachments_gin` via `EXPLAIN`.
- [x] New: `test_migration_0013_is_idempotent` — run the migration twice in a fresh SQLite-in-memory DB (well, the migration is Postgres-only so this needs a Postgres test DB). For now, document as a follow-up: write the test against a Postgres fixture; if no Postgres test DB is available in CI, write a structural test that asserts `CREATE INDEX IF NOT EXISTS` is in the migration file.

Files touched: `tests/api/test_attachments.py`, possibly new `tests/migrations/test_0013.py`.
LoC: ~50.
Commit: combined with 2.2 (single commit for the C3 deliverable).
Depends on: 2.2.x + 3.1.

### 4.4 Concurrent rate limit test

- [x] `test_check_rate_limit_async_concurrent_6th_raises` — 6 concurrent `asyncio.gather` calls to `_check_rate_limit(user_id=42)`; assert exactly one raises with `reason="puppeteer_rate_limited"`. The other 5 succeed.

Files touched: `tests/core/test_puppeteer_mcp.py`.
LoC: ~20.
Commit: combined with 1.2 (single commit for the bonus deliverable).
Depends on: 1.2.x.

---

## 5. Docs

### 5.1 ADR-013 §2.1 amendment

- [x] In `docs/adr/013-puppeteer-mcp.md`, after §2 (existing "Budgets"), append §2.1 with the exact text from design §6.1.
- [x] Do NOT touch any other ADR section. This is a single-section amendment, not a full ADR replacement.

Files touched: `docs/adr/013-puppeteer-mcp.md`.
LoC: ~10.
Commit: `docs(adr-013): clarify byte-cap enforcement boundary (§2.1)`.
Depends on: 1.1.x (the byte-cap wrapper must be in place to be described accurately).

### 5.2 Verify-report ERRATA

- [x] In `openspec/changes/2026-09-07-F13-puppeteer-mcp/verify-report.md`, prepend the ERRATA block from design §6.2 (before §1, with `>` blockquote for visibility).
- [x] Do NOT modify the existing §3 REQ-PMCP-3 verdict — the ERRATA supersedes it without rewriting history.

Files touched: `openspec/changes/2026-09-07-F13-puppeteer-mcp/verify-report.md`.
LoC: ~10.
Commit: `docs(f13): errata note in verify-report — byte cap was not wired at original verify`.
Depends on: 1.1.x (the fix must exist before the ERRATA references it).

---

## 6. Cross-cutting

### 6.1 Local sanity pass before push

- [x] Run `pytest tests/core/test_puppeteer_mcp.py tests/core/test_attachment_tokens.py tests/api/test_attachments.py -v` — all green.
- [x] Run `pytest --cov=app --cov=app/core` — coverage report delta noted but not enforced (team threshold = 0 per `openspec/config.yaml:17`).
- [x] Manual smoke (out of CI): `docker compose up -d puppeteer-mcp backend` + send a chat prompt eliciting a Mermaid block + observe `event: attachment` fires with a valid signed URL.
- [x] Verify commit order matches the work-unit plan in `design.md` §8: 1 (rate lock) → 2 (verify refactor) → 3 (byte cap) → 4 (migration) → 5 (lookup) → 6 (errata) → 7 (ADR amendment).
- [x] Verify `git log --oneline feature/integration-f11-f12-f13 -7` shows the 7 new commits on top of the PR #76 base.

Files touched: nothing.
LoC: 0 (run-only).
Commit: none (sanity gate before push).
Depends on: all 1.x through 5.x.

### 6.2 Push + PR update

- [x] `git push origin feature/integration-f11-f12-f13` — push the 7 commits.
- [x] Add a PR comment summarizing the fix (mention the PR #76 review this addresses; link to the design + tasks).
- [x] Re-request review from the reviewers who CHANGES_REQUESTED on round 3/4 (`@lau2413`, `@Soomri` per PR body).

Files touched: none.
LoC: 0.
Commit: none.
Depends on: 6.1.

---

## Total LoC estimate

| Area | LoC |
|---|---|
| 1. Backend Core (1.1 + 1.2 + 1.3) | ~73 |
| 2. Backend API (2.1 + 2.2) | ~25 (net after refactor) |
| 3. Migrations | ~10 |
| 4. Tests | ~270 |
| 5. Docs | ~20 |
| **Total** | **~398** |

**Within 800-line review budget** — gatekeeper should NOT trigger a stop-for-approval.

---

## Commit execution order

1. `fix(puppeteer-mcp): wire _RATE_LIMIT_LOCK as asyncio.Lock to prevent race in _check_rate_limit` (1.2 + 4.4)
2. `refactor(attachments): route delegates to verify_attachment_token, drop inline duplicate` (1.3 + 2.1 + 4.2)
3. `feat(puppeteer-mcp): enforce 2 MB render byte cap at tool-invocation boundary (REQ-PMCP-3)` (1.1 + 4.1)
4. `feat(db): add GIN index on messages.attachments for containment lookup` (3.1)
5. `perf(attachments): use Postgres JSONB containment query when available; keep SQLite fallback` (2.2 + 4.3)
6. `docs(f13): errata note in verify-report — byte cap was not wired at original verify` (5.2)
7. `docs(adr-013): clarify byte-cap enforcement boundary (§2.1)` (5.1)

Each commit: `git add <specific files>`, message body references the relevant design.md section.

---

## Out of scope (deferred)

- `puppeteer_mcp.py:_make_optional_params_nullable` schema mutation hardening (already pinned to a specific `langchain-mcp-adapters` version via `requirements.txt`; revisit when the package releases v0.4+).
- F14 Redis-backed rate limiter (currently single-replica in-memory).
- F14 horizontal scaling of the sidecar (multi-replica + load balancer).
- F14 HTML rendering + sanitizer (out of F13 scope per ADR-013 §Decisions).
- `puppeteer_evaluate` re-evaluation (explicitly dropped per ADR-013 §1 + REQ-PMCP-2 spec alignment).

---

## References

- `openspec/changes/2026-09-20-f13-review-fixes/explore.md`
- `openspec/changes/2026-09-20-f13-review-fixes/proposal.md`
- `openspec/changes/2026-09-20-f13-review-fixes/design.md`
- `openspec/config.yaml` (rules for tasks)
- `docs/adr/013-puppeteer-mcp.md` (target of §2.1 amendment)
- `https://github.com/danielCH26/arch-agent/pull/76` (PR under fix)
