# Proposal: F13 PR #76 Review Fixes

| Field | Value |
|---|---|
| Branch | `feature/integration-f11-f12-f13` — fix commits append directly to PR #76 (single PR, no further stacking) |
| Delivery | `single-pr`; work-unit commits, one per finding |
| ADR impact | ADR-013 §2 clarification note (see below) |

## Intent

Close the three audit findings from PR #76's review of F13: the unimplemented 2 MB render byte cap (REQ-PMCP-3 partial fail), the dead `verify_attachment_token` helper duplicated inline by the route, and the un-paginated attachments lookup that is both a DoS vector and lacks its GIN index.

## Key Decision — C1: implement the cap

**Decision: `implement-cap`** (confirms explore's recommendation).

Refutation of the "timeout + rate limit is enough" alternative: the two existing guards are orthogonal, not redundant. The 15 s timeout bounds the `get_tools` metadata fetch; the 5/min limit bounds frequency; **neither bounds render amplitude**. A single fast render returning a 50 MB PNG passes both today, is written to `/app/uploads/screenshots/`, and is re-served on every attachment fetch. Dropping the cap would also cost *more* artifact churn than implementing it (spec REMOVED delta + ADR-013 §2 amendment + errata) versus ~30 LoC + one test in one file.

Honest limitation (design must record): a post-hoc check on the received tool result bounds what is **persisted and served**, not receive-time memory (the bytes are already in process when measured). Transport-time memory remains bounded by the sidecar `mem_limit: 512m`.

## Scope

### In Scope
- **C1**: `_MAX_RENDER_BYTES = 2097152` constant + render-result size guard raising `PuppeteerUnavailable(reason="puppeteer_byte_cap")`. Enforced at the tool-invocation boundary, NOT the `get_tools` fetch.
- **C2**: route delegates to `verify_attachment_token` (typed result per explore); route uses `DEFAULT_TTL_SECONDS` (verified `== 300` — behavior-neutral); inline duplicate deleted.
- **C3**: new GIN migration — **`0013` is the free slot** (disk: 0012→0014 jump; explore §4's `0015_*` contradicts its own §6, normalize on 0013) + Postgres containment query, keeping the Python-filter fallback for SQLite tests.
- **Bonus**: `_RATE_LIMIT_LOCK` wired as a real `asyncio.Lock` in `_check_rate_limit` (latent multi-worker race, one-line fix).
- **Errata**: note in `2026-09-07-F13-puppeteer-mcp/verify-report.md` correcting the false "byte cap wired" claim (§3 REQ-PMCP-3 verdict).

### Out of Scope
- F14: horizontal rate-limit scaling, Redis migration, HTML rendering/sanitizer.
- Frontend changes (already in PR #76).

### Adjacent issues deferred
- The 15 s timeout guards only the tool fetch; the render invocation itself has no independent timeout (observed during propose). Design should note it; fixing stays out of this slice.

## Capabilities

### New Capabilities
None.

### Modified Capabilities
None — REQ-PMCP-3 already specifies the cap (code moves to meet spec); C2/C3 preserve REQ-ATT-2 semantics (200/401/404, TTL ≤ 5 min). Spec phase is a no-op.

## Approach

Follow explore §5: per-finding work-unit commits mirroring existing patterns (`_FETCH_TIMEOUT_SECONDS` constant style; `0012_*` migration precedent; existing test fixtures). Exact byte-cap mechanism (tool wrapper vs. consumption-point guard) is design's decision.

## Affected Areas

| Area | Impact |
|---|---|
| `app/core/puppeteer_mcp.py` | Modified — byte cap + rate-limit lock |
| `app/api/attachments.py` | Modified — delegate to helper; indexed containment query |
| `app/core/attachment_tokens.py` | Modified — helper signature for route use |
| `migrations/0013_add_message_attachments_gin.sql`, `schema.sql` | New / Modified — GIN index + mirror |
| `tests/core/test_puppeteer_mcp.py`, `tests/core/test_attachment_tokens.py`, `tests/api/test_attachments.py` | Modified — coverage for all fixes |
| `openspec/changes/2026-09-07-F13-puppeteer-mcp/verify-report.md` | Modified — ERRATA note |

## Spec & ADR Impact

| Artifact | Change |
|---|---|
| `openspec/specs/puppeteer-mcp-integration/spec.md` | None (implementation closes the gap; requirement text already correct) |
| `openspec/specs/chat-attachments/spec.md` | None (C2/C3 are implementation-level) |
| ADR-013 §2 | One clarifying sentence: the cap bounds the persisted/served artifact; receive-time memory is bounded by the sidecar `mem_limit`. (Had C1 been dropped-from-spec, §2 would need a full amendment instead.) |

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Byte cap enforced at wrong boundary (fetch vs invocation) | Med | Proposal pins the boundary; design pins the mechanism |
| `contains()` unsupported on SQLite test DB | Med | Retain Python-filter fallback behind dialect check |
| Plain `CREATE INDEX` locks `messages` briefly | Low | Runner is transaction-per-file → `CONCURRENTLY` unusable; table is small, lock is brief — accept and document |
| Render latency change from cap check | Low | O(len) check on an in-memory string — negligible |

## Rollback Plan

Each finding is its own conventional commit: `git revert <sha>` cleanly undoes any single piece. Migration `0013` is `CREATE INDEX IF NOT EXISTS` → rollback is `DROP INDEX IF EXISTS idx_messages_attachments_gin`. No data transforms, no destructive deltas.

## Dependencies

- PR #76 stays open; these commits append to it.

## Success Criteria

- [ ] Oversized render raises `PuppeteerUnavailable(reason="puppeteer_byte_cap")` (unit test)
- [ ] Route calls `verify_attachment_token`; no inline duplicate remains
- [ ] Postgres path uses the indexed containment lookup; SQLite tests pass unchanged
- [ ] `_RATE_LIMIT_LOCK` is actually acquired in `_check_rate_limit`
- [ ] verify-report ERRATA present; full `pytest` shows no new failures
