```yaml
schema: gentle-ai.verify-result/v1
evidence_revision: sha256:d94ecfbc9e4d1fd93a663bfa6be3f1bb0312adadab6a082ccba23b0084648baa
verdict: pass
blockers: 0
critical_findings: 0
requirements: 10/10
scenarios: 10/10
test_command: python3 -m pytest tests/core/test_puppeteer_mcp.py tests/core/test_attachment_tokens.py tests/api/test_attachments.py --tb=short -q
test_exit_code: 0
test_output_hash: sha256:d94ecfbc9e4d1fd93a663bfa6be3f1bb0312adadab6a082ccba23b0084648baa
build_command: python3 -m py_compile app/core/puppeteer_mcp.py app/core/attachment_tokens.py app/api/attachments.py app/core/agent.py
build_exit_code: 0
build_output_hash: sha256:122ab9852e71f68ad3e0282aa467aab6bf145be71b4850109103660e61b505ff
```

# Verify Report: F13 PR #76 Review Fixes

## Summary
- **Verdict**: PASS
- **Date**: 2026-09-19
- **Branch**: `feature/integration-f11-f12-f13`
- **Commits verified**: 7 work commits (`793131e`, `e417d8e`, `7340f67`, `e200587`, `2096bbc`, `1fcbe3a`, `e8191f5`) + follow-up `440cea0` (tasks.md checkboxes). HEAD verified: `440cea0`; all touched files confirmed committed and clean in the working tree.
- **Scope**: per-REQ verification of the 6 affected requirements (REQ-PMCP-2/3/4/5, REQ-ATT-1/2) plus 4 new deliverables (C3 GIN migration, ADR-013 §2.1, verify-report ERRATA, `verify_attachment_token` unit tests). REQ-PMCP-1 and REQ-ATT-3 are out of this change's diff; both incidentally re-confirmed green (3 chat-level attachment tests passed).

## Test results
- pytest `tests/core/test_puppeteer_mcp.py`: 28 passed, 1 skipped (`test_get_puppeteer_tools_live` — gated behind `PUPPETEER_LIVE_TEST`)
- pytest `tests/core/test_attachment_tokens.py`: 7 passed
- pytest `tests/api/test_attachments.py`: 7 passed
- **Total: 42 passed, 1 skipped** — exit code 0
- Supplementary runtime evidence: `pytest tests/api/test_chat.py -k attachment` → 3 passed (atomic persist + SSE attachment-event ordering, REQ-ATT-1/REQ-PMCP-1 regression)
- Supplementary runtime probe (SCN-ATT-4 spec letter): session user 2 with own valid token, attachment row owned by user 1 → **404** confirmed against committed code
- Build proxy: `py_compile` on the 4 touched app files → exit 0

## REQ-by-REQ verdict
| REQ | Status | Evidence |
|-----|--------|----------|
| REQ-PMCP-3 | PASS | 15s timeout: `_FETCH_TIMEOUT_SECONDS = 15.0` (`puppeteer_mcp.py:49`) + `asyncio.wait_for(...)` (lines 377–380) → `PuppeteerUnavailable(reason="puppeteer_timeout")`; 2 MB cap: `_DEFAULT_MAX_RENDER_BYTES = 2_097_152` (line 81), `_max_render_bytes()`, `_measure_result_bytes()`, `_wrap_tool_with_byte_cap()` (lines 192–227) wired in `get_puppeteer_tools` post schema-widening loop (lines 429–430); 7 byte-cap tests + timeout test green |
| REQ-PMCP-2 | PASS | `_PUPPETEER_ALLOWED_TOOLS = frozenset({"puppeteer_screenshot"})` intact (`puppeteer_mcp.py:66`), filter at line 396; `test_get_puppeteer_tools_allow_list_filters_navigate_etc` green |
| REQ-ATT-2 | PASS | Route delegates to `verify_attachment_token(token, attachment_id=id, user_id=user_id)` (`attachments.py:68–72`), no inline itsdangerous duplicate remains; helper returns `tuple[bool, int \| None]` with required `user_id` kwarg (`attachment_tokens.py:91–137`); 401 missing/forged/cross-aid tests + helper-level expired test green; 404 cross-user confirmed (probe) + `test_404_unknown_id_even_with_valid_token` green; no-WARNING-on-404 test green |
| REQ-ATT-1 | PASS | `_persist_turn` (`chat.py:266–303`): `save_message(user)` + `save_message(assistant, attachments=…)` + single `db.commit()` (line 295); `SQLAlchemyError` → `event: error` "messages store unavailable"; untouched by this change; `test_chat_stream_attachments_persisted_atomically_in_pre_done_tx` green |
| REQ-PMCP-4 | PASS | 5/min default + 60s sliding window intact; `_RATE_LIMIT_LOCK = asyncio.Lock()` (line 77), `async def _check_rate_limit` with `async with _RATE_LIMIT_LOCK:` (lines 111–157) raising `PuppeteerUnavailable(reason="puppeteer_rate_limited")`; caller awaits (`agent.py:255`); 5 rate tests incl. NEW `test_check_rate_limit_async_concurrent_6th_raises` green |
| REQ-PMCP-5 | PASS | Langfuse wiring intact: `chat.py:178–181` appends `get_langfuse_handler()` to callbacks (F11 wiring, untouched); inspection spot-check per orchestrator instruction — no runtime span test exists (inherited posture from PR #76) |
| C3 GIN migration | PASS | `migrations/0013_add_message_attachments_gin_index.sql` exists with exactly `CREATE INDEX IF NOT EXISTS idx_messages_attachments_gin ON messages USING GIN (attachments jsonb_path_ops);` — idempotent |
| ADR-013 §2.1 | PASS | Amendment present at `docs/adr/013-puppeteer-mcp.md:73–80`, immediately after §2, text matches design §6.1; rest of ADR untouched |
| verify-report ERRATA | PASS | Blockquote ERRATA block at top of `openspec/changes/2026-09-07-F13-puppeteer-mcp/verify-report.md` (lines 16–26, before §1); original §3 verdict preserved verbatim |
| verify_attachment_token unit tests | PASS | All 7 tests present in `tests/core/test_attachment_tokens.py` and green: good token → `(True, uid)`; expired / bad signature / mismatched aid / mismatched uid / empty token / non-dict payload → `(False, None)` |

## Spec compliance matrix (affected scenarios)
| Scenario | Test | Result |
|----------|------|--------|
| SCN-PMCP-3 | `test_get_puppeteer_tools_allow_list_filters_navigate_etc` | ✅ COMPLIANT |
| SCN-PMCP-4 | `test_get_puppeteer_tools_timeout_raises` | ✅ COMPLIANT |
| SCN-PMCP-5 | `test_wrap_tool_with_byte_cap_raises_over_limit` + 6 more cap tests | ✅ COMPLIANT |
| SCN-PMCP-6 | `test_rate_limit_allows_5_calls_in_60s`, `test_check_rate_limit_async_concurrent_6th_raises`, … | ✅ COMPLIANT |
| SCN-ATT-1 / SCN-ATT-2 | `test_chat_stream_attachments_persisted_atomically_in_pre_done_tx` | ✅ COMPLIANT |
| SCN-ATT-3 | `test_200_happy_path` | ✅ COMPLIANT |
| SCN-ATT-4 | runtime probe (404 on cross-user row) + `test_404_unknown_id_even_with_valid_token` (same lookup-miss branch) | ✅ COMPLIANT |
| SCN-ATT-5 | `test_401_missing_token`, `test_401_forged_token`, `test_401_cross_attachment_id` + helper-level expired test | ✅ COMPLIANT |
| SCN-ATT-6 | `test_200_happy_path` (Content-Disposition assertions, lines 280–282) | ✅ COMPLIANT |
| SCN-PMCP-7 | (no automated test exists — inherited from PR #76) | ⚠️ INSPECTION-VERIFIED (wiring intact, out of diff scope) |

**Compliance summary**: 10/10 in-scope scenarios runtime-compliant; SCN-PMCP-7 inspection-only (unchanged Langfuse wiring; same posture as the original F13 verify).

## Coherence (design)
| Decision | Followed? | Notes |
|----------|-----------|-------|
| C1 cap at tool-invocation boundary (post-`ainvoke`) | ✅ Yes | `_wrap_tool_with_byte_cap` replaces `tool.ainvoke`; disabled when env = 0 |
| C2 helper returns `(bool, int \| None)`, route delegates | ✅ Yes | Route 401 mapping identical; `get_current_user` dependency added per design §3.2 |
| C3 dialect-aware `_lookup_attachment` + 0013 migration | ✅ Yes | Postgres containment + SQLite Python-filter fallback |
| Bonus: `asyncio.Lock` in `_check_rate_limit` | ✅ Yes | Plus defensive `hasattr(tool, "ainvoke")` guard in wrapper (harmless addition) |
| Docs: §2.1 amendment + ERRATA | ✅ Yes | Both present, verbatim per design §6.1/§6.2 |

## Deviations / follow-ups
1. **WARNING — tasks 4.3 Postgres-gated tests not present**: `test_attachments_lookup_uses_postgres_containment_when_available` (EXPLAIN-based) and the migration idempotency test do not exist anywhere in `tests/` (grep confirms zero references to `idx_messages_attachments_gin` / `0013` / `is_postgres`). tasks.md marks 4.3 complete under its own documented escape hatch ("document as a follow-up… structural test"), but no structural test was written either. The Postgres containment branch is runtime-unverified; only the SQLite fallback is tested. Follow-up: add the structural migration test (assert `CREATE INDEX IF NOT EXISTS` in file) — needs no Postgres DB.
2. **WARNING — `test_404_cross_user` re-scoped**: pre-refactor it asserted "user 2's own valid token + user 1's row → 404"; it now asserts "user 1's token + user 2's session → 401" (a NEW, stricter token↔session check from design §3.1). The spec-letter SCN-ATT-4 behavior (404 on cross-user row) still holds — proven by an out-of-repo runtime probe against the committed code and structurally covered by the lookup-miss test — but no dedicated in-repo test fixture asserts it anymore. Follow-up: restore an explicit SCN-ATT-4 test. Note: the old route would have returned **200** for a cross-session replayed token (no session dependency existed); returning 401 is strictly safer and does not leak existence.
3. **SUGGESTION — naming drift**: design.md/tasks.md reference `_make_optional_params_nullable`, but the actual function is `_widen_optional_schema_params` (a stale reference also survives in the `puppeteer_mcp.py:202` docstring). Cosmetic only.
4. **SUGGESTION — route-level expired-token test**: expired-token → 401 is covered at helper level (`test_verify_returns_false_none_on_expired`) but not at route level; the route maps every `(False, None)` to a uniform 401, so risk is minimal.

## Archive readiness
All in-scope REQs and deliverables PASS → ready for archive after PR #76 merges. Two WARNING-class test-coverage follow-ups (Postgres-gated EXPLAIN test, explicit SCN-ATT-4 fixture) are non-blocking and tracked above.
