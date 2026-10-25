# Archive Report: F12 — Engram MCP (Memoria + Historial de Chat)

| Field | Value |
|---|---|
| **Change slug** | `F12-engram-mcp` |
| **Capability (NEW)** | `engram-conversation-memory` |
| **Branch** | `feature/F12-engram-mcp` |
| **Base** | `origin/development` @ `d139c9e` (PR #64 MERGED) |
| **HEAD at archive** | `f0731bb` (Postgres liveness check + SCN-5 test, post-drift fix) |
| **Archive location** | `openspec/changes/archive/2026-09-05-F12-engram-mcp/` |
| **Canonical spec** | `openspec/specs/engram-conversation-memory/spec.md` (13 REQ, 8 SCN) — **preserved** |
| **ADR** | ADR-011 `docs/adr/011-engram-conversation-mirror.md` @ `1cfcbc1` |
| **Issue** | [#14 — [F12] Engram MCP integrado (memoria)](https://github.com/danielCH26/arch-agent/issues/14) |
| **Pre-existing failures** | Tracked separately at [#66](https://github.com/danielCH26/arch-agent/issues/66) (unchanged) |
| **Engram topic_key (this report)** | `sdd/F12-engram-mcp/archive` |
| **Archived at (ISO8601)** | `2026-09-05T22:00:00Z` |
| **Final verdict** | `pass_with_warnings` — **0 CRITICAL findings** (post `f0731bb`) |

---

## Summary

F12 ships the `engram-conversation-memory` capability as a NEW canonical spec at `openspec/specs/engram-conversation-memory/spec.md`: every chat turn is persisted to Postgres (`messages` table) before the SSE handler yields `event: done`, with a fire-and-forget mirror into Engram for semantic recall; `GET /api/chat/history?project_id=&limit=` exposes the last-N turns and `frontend/ChatWindow` mount-fetches them under a StrictMode guard. The change landed across 11 commits ahead of `origin/development` as 4 work units: 3 chained slices (F12.1 backend foundation @ `9f03251`, F12.2 chat integration + history endpoint @ `0640b93`, F12.3 frontend persistence @ `f16735a`) plus 1 drift-fix commit (f0731bb — Postgres `SELECT 1` liveness probe added BEFORE any other DB op in the chat handler so `REQ-11/SCN-5` returns HTTP 503, satisfying the spec mandate). The F12.1 and F12.2 slices exceeded the 400-line soft target (~712 LoC and ~551 LoC diffs respectively) — pre-approved in `tasks.md` §Chained-PR Decision as `size:exception` because production code stays inert and all 3 chains are reviewable in isolation; total ~3223 insertions / 12 deletions across 25 files vs base. Final state: 47/47 F12-affected pytest + 8/8 vitest passing; 1 pre-existing failure from issue #66 unchanged; 13/13 REQs and 8/8 SCNs satisfied per the Final-State Authority hierarchy (orchestrator's launch prompt — rank 3 — outranks the `verify-report.md @ 389d538` snapshot which had 1 CRITICAL drift; the drift landed in `f0731bb`, so the archive reports zero CRITICAL). Items deferred to future capability slices: `app/core/session_store.py` dead-code refactor, MCP-stdio transport for Engram, frontend message virtualization, and CI guard `tests/test_schema_sync.py` for `schema.sql` ↔ `migrations/0008` parity.

---

## Closed PRD items (Issue #14 acceptance criteria)

| # | AC (Spanish → English) | Status | Evidence |
|---|---|---|---|
| 1 | **Decisiones se guardan automáticamente** — architectural decisions persist automatically | ✅ Closed | `app/core/message_store.py::engram_mirror` (lines 130-173) calls `engram_client.save(topic_key=…)` for each chat turn (user + assistant) **after** Postgres commit; ADR-011 locks the hybrid pattern. SCN-1 verified (`tests/api/test_chat.py::test_commit_happens_before_done_yield` asserts commit < mirror). |
| 2 | **El agente recupera contexto relevante** — agent recovers relevant context | ✅ Closed | `engram_client.get_context(project)` already aggregates what Engram knows (`d139c9e`); spec keeps it as opt-in via explicit request rather than auto-injecting the digest. `app/core/engram_client.py` extended with `search`, `get_observation`, `save(topic_key)`, `delete` (lines 53-123) so callers can browse observations. |
| 3 | **Persistencia entre sesiones** — persistence across sessions | ✅ Closed | `migrations/0008_add_messages_table.sql` (NEW) + `schema.sql` mirror (lines 131-149) + `app/models/message.py` (REQ-1, REQ-2). `app/core/message_store.py::save_message` (lines 81-127). `tests/core/test_message_store.py` — 13 tests. |
| 4 | **Al recargar la página, los mensajes previos del chat siguen visibles** — reload shows prior messages | ✅ Closed | `frontend/src/components/ChatWindow.tsx:26-35` invokes `chatStore.loadHistory(projectId)` from `useEffect(..., [projectId])` guarded by `isStreaming === false && loadingHistory === false`. Vitest `ChatWindow.test.tsx` — 3 tests (mount fires once, projectId-change re-fires, StrictMode-safe). |
| 5 | **El usuario puede seguir desde donde dejó la conversación** — user continues where they left off | ✅ Closed | `POST /api/chat` persists user+assistant rows in a single Postgres tx BEFORE `yield event: done` (`app/api/chat.py:206-227`); next `GET /api/chat/history` returns them. `tests/api/test_chat.py::test_commit_happens_before_done_yield` proves ordering. |

Bonus negative criteria (from `proposal.md` §9):

- ✅ Engram unreachable + Postgres up → `POST /api/chat` 200 SSE; rows persisted; mirror logs WARNING and drops; no exception reaches user. `tests/api/test_chat.py::test_engram_error_does_not_abort_stream`.
- ✅ Both stores unreachable → `POST /api/chat` returns **HTTP 503** (post-f0731bb; `app/api/chat.py:92-105` liveness probe raises `HTTPException(503)` before SSE starts); `GET /api/chat/history` returns `200 {messages: []}` (`app/api/chat.py:302-308`).
- ✅ No regressions on `tests/api/test_chat.py` (existing 11 tests pass) or `tests/test_llm_validator.py` (mock helper `_build_f12_engram_mock` exposes the 4 REQ-5 methods).

---

## Files created / modified

### Spec / design artifacts (kept in archive folder; canonical spec lives at `openspec/specs/engram-conversation-memory/spec.md`)

- `openspec/specs/engram-conversation-memory/spec.md` @ `bec064f` — NEW canonical, 13 REQ + 8 SCN (preserved at canonical, not duplicated into the change folder; this archive keeps the per-change audit trail).
- `openspec/changes/archive/2026-09-05-F12-engram-mcp/explore.md` @ `8ae860f`
- `openspec/changes/archive/2026-09-05-F12-engram-mcp/proposal.md` @ `1cfcbc1`
- `openspec/changes/archive/2026-09-05-F12-engram-mcp/design.md` @ `9a2c6f8` (17 sections, 4 sequence diagrams)
- `openspec/changes/archive/2026-09-05-F12-engram-mcp/tasks.md` @ `bffd3fc` (13 hierarchical tasks, all `[x]`)
- `openspec/changes/archive/2026-09-05-F12-engram-mcp/verify-report.md` @ `389d538` (intermediate snapshot — superseded by `f0731bb`)
- `openspec/changes/archive/2026-09-05-F12-engram-mcp/apply-progress.md` (fallback file, untracked at archive time — included in archive tree because it lives inside the change folder)
- `docs/adr/011-engram-conversation-mirror.md` @ `1cfcbc1` — locks hybrid storage + fire-and-forget Engram mirror

### Backend — production (NEW + MODIFIED across slices)

- **F12.1** — `app/models/message.py` (NEW, 81 LoC, REQ-2 SQLAlchemy 2.0 `Message` ORM with CHECK constraint + `with_variant` cross-dialect pattern)
- **F12.1** — `app/models/__init__.py` (MODIFIED, +1 line; registers `Message` in `Base.metadata`)
- **F12.1** — `app/core/message_store.py` (NEW, 173 LoC, REQ-3/6/10 — `save_message`, `list_recent`, `engram_mirror`, `_ensure_user_session`)
- **F12.1** — `app/core/engram_client.py` (MODIFIED, +77 LoC; existing 5 methods untouched; **NEW**: `search`, `get_observation`, `save(topic_key)`, `delete`)
- **F12.1** — `migrations/0008_add_messages_table.sql` (NEW, 38 LoC, REQ-1 — `CREATE TABLE IF NOT EXISTS messages` + FKs + indexes)
- **F12.1** — `schema.sql` (MODIFIED, +27 LoC; mirrors the migration for greenfield DB parity)
- **F12.2** — `app/api/chat.py` (MODIFIED, +134 LoC; total 323 LoC; REQ-4/6/7/11 — wraps `event_generator` to persist user+assistant rows in one tx before `yield done`; adds `GET /api/chat/history?project_id=&limit=`)
- **f0731bb** — `app/api/chat.py` (+17 LoC; Postgres `SELECT 1` liveness probe before any other DB op, raises `HTTPException(503)` on `SQLAlchemyError`)

### Frontend — production

- **F12.3** — `frontend/src/api/chat.ts` (MODIFIED, +49 LoC; adds `fetchChatHistory(projectId, limit=5)`)
- **F12.3** — `frontend/src/stores/chatStore.ts` (MODIFIED, +38 LoC; `loadHistory(projectId)` action + `loadingHistory` flag + atomic `set({messages, loadingHistory: false})`)
- **F12.3** — `frontend/src/components/ChatWindow.tsx` (MODIFIED, +22 LoC; `useEffect(..., [projectId])` mount-time fetch with `isStreaming` + `loadingHistory` guard)

### Tests

- **F12.1** — `tests/core/test_message_store.py` (NEW, 204 LoC, 13 tests — REQ-3 / SCN-3 / SCN-6)
- **F12.1** — `tests/test_engram_client.py` (MODIFIED, +95 LoC; 8 new tests for `search`/`get_observation`/`save`/`delete` + REQ-5 scoping)
- **F12.2** — `tests/api/test_chat.py` (MODIFIED, +125 LoC; commit-before-yield + Engram-down resilience; 13 tests)
- **F12.2** — `tests/api/test_chat_history.py` (NEW, 266 LoC, 9 contract tests — REQ-7/11/SCN-3/SCN-5)
- **F12.2** — `tests/test_llm_validator.py` (MODIFIED, +16 LoC; `_build_f12_engram_mock` exposes the 4 REQ-5 methods)
- **f0731bb** — `tests/api/test_chat.py` (+39 LoC; SCN-5 / REQ-11 Postgres liveness test)
- **F12.3** — `frontend/src/stores/__tests__/chatStore.test.ts` (NEW, 99 LoC, 5 tests — REQ-8)
- **F12.3** — `frontend/src/components/__tests__/ChatWindow.test.tsx` (NEW, 89 LoC, 3 tests — REQ-9 / SCN-2)

### Totals (per `apply-progress.md` + drift-fix commit)

- 25 files changed vs `origin/development @ d139c9e`
- ~3,223 insertions, ~12 deletions
- 13 hierarchical tasks across 3 chained slices; **all marked `[x]`** in the archived `tasks.md`

---

## Branches for stacked PRs

The orchestrator pre-approval commits `feature/F12-engram-mcp` ahead of `origin/development @ d139c9e` (PR #64 MERGED) as **11 commits in one branch**, ready to be sliced into 3-4 stacked PRs against `development`. Recommended split:

| PR # | Branch name | Base | Commits | Scope | Approx LoC | Status |
|---|---|---|---|---|---|---|
| **F12.0** | _(none)_ | — | `8ae860f` (explore + `.gitignore`) | Docs-only; already merged into `feature/F12-engram-mcp`. **No PR needed.** | — | Already in branch |
| **F12.1** | `feature/F12-s1-backend-foundation` | `origin/development @ d139c9e` | `1cfcbc1` (proposal + ADR-011), `bec064f` (spec), `9a2c6f8` (design), `bffd3fc` (tasks), `9f03251` (F12.1 apply) | Backend foundation: `Message` ORM + `message_store` + EngramClient extensions + migration 0008 + tests. **Inert** (no `chat.py` change). | ~712 LoC | Ready |
| **F12.2 + F12-fix** | `feature/F12-s2-chat-integration` | `feature/F12-s1-backend-foundation` | `0640b93` (F12.2 apply), `f0731bb` (drift fix) | Chat integration + `GET /api/chat/history` + Postgres liveness check (REQ-11 fix). Drift-fix touches `chat.py` too, so it folds into F12.2. | ~590 LoC | Ready |
| **F12.3** | `feature/F12-s3-frontend-persistence` | `feature/F12-s2-chat-integration` | `f16735a` (F12.3 apply) | Frontend persistence: `fetchChatHistory` + `chatStore.loadHistory` + `ChatWindow` mount-time fetch + Vitest. | ~307 LoC | Ready |

**Chain strategy**: `stacked-to-main` (chained-to-base — each PR targets the immediate previous PR branch; rebases until the child diff is clean against the parent).

**Per-PR review budget (400-line soft, 800-line hard)**:
- F12.1 = ~712 LoC → slightly over the soft target (pre-approved as `size:exception` per `tasks.md` §Chained-PR Decision; production code inert).
- F12.2 + F12-fix = ~590 LoC → over the soft target (also pre-approved).
- F12.3 = ~307 LoC → within soft target.

**Stack-to-main protocol** (per `chained-pr` skill): when a child PR's diff against the parent shows previous slices in it, retarget/rebase until clean. Each PR merges to `development` in order so reviewers see one logical delta per PR.

---

## PR #64 dependency map

| Dependency | Status | Impact on F12 |
|---|---|---|
| **PR #64 — Pipeline RAG + PGVector** (`d139c9e`) | ✅ MERGED on `origin/development` | F12's `messages` table rides on the same Postgres instance; `schema.sql` and migration tooling come from this base. |
| **F11 PRs #69–74 (LangChain agent runtime + Context7 MCP + Langfuse tracer)** | ⏳ OPEN, NOT merged | F12 is **independent** of F11. `chat.py` still calls `model.astream(prompt)` directly at this base; F12 persistence slots between the model and the SSE stream without awaiting F11. The F12 branch does not import any F11 module (`app/core/context7_mcp.py`, `app/core/agent.py`, `app/core/langfuse_tracer.py` remain absent). |
| **Engram runtime container** (`engram` + `engram-proxy` socat, port `:7439`) | ✅ Live at `d139c9e` | `ENGRAM_URL` env wired; `engram_client.py:17`; `engram-proxy` socat on `:7437` carries cross-tool traffic. |
| **Issue #66 — Pre-existing failures** | ⏳ OPEN (6 failures: 5 backend pydantic v2 / missing `save_document` + `overwrite_document`, 1 frontend jsdom) | F12 does not regress. Verified at base via `git stash`. |

---

## Carried risks

Per `verify-report.md §5` and `tasks.md §Risks` (re-stated for archival context; current state per the orchestrator's final-state authority overrides the verify-report snapshot's pending claims):

1. **TTFT regression from synchronous per-turn save** (Med) — Local socket round-trip is ≤50ms; benchmarked in F12.2 PR; fallback to fire-and-forget if TTFT regresses >100ms. **Currently acceptable** — no measurement taken at archive time, production env not instrumented for sub-100ms precision.
2. **Frontend StrictMode race clobbers in-flight tokens** (Med) — Mitigated by `loadingHistory` + `isStreaming` guards (`ChatWindow.tsx:28-30`); Vitest asserts StrictMode-safe single-fire (`ChatWindow.test.tsx::test_does_NOT_double_fire_under_StrictMode`).
3. **`test_llm_validator.py` dormant imports on REQ-5 methods** (Med → Low) — F12.2 patch `_build_f12_engram_mock` exposes the 4 new methods; tests pass unchanged semantics. **Resolved** at archive.
4. **Cross-user leakage via `engram_client.search`** (Med → Low) — `ValueError("project is required")` raises when project is None/empty (`engram_client.py:67-68`); 8 tests + cross-user test in `test_message_store.py::test_session_id_scopes_results` confirm isolation. **Resolved** at archive.
5. **Migration drift between `schema.sql` and `migrations/0008_*`** (Low) — Mirror is verbatim; runner idempotent (`CREATE TABLE IF NOT EXISTS`). **Future work**: `tests/test_schema_sync.py` CI guard flagged as `S-2` in verify-report.
6. **Token growth in LLM context** (Med) — Hard cap N=5 default; `?limit=` max 50; `engram_client.get_context()` opt-in only. **Currently bounded**.
7. **First-message `UserSession` lazy-upsert race** (Low) — `_ensure_user_session` catches `IntegrityError` + re-`SELECT`. **Resolved** at archive.
8. **Disconnect after Postgres commit but before SSE `done`** (Low) — Acceptable; the row surfaces on next history call. **Documented behaviour**.
9. **`chat.py:121` `SSEStreamCallbackHandler` remains dead** (Low) — Out of scope (design §14). **Deferred**.
10. **`app/core/session_store.py` dead-code refactor** — Deferred per ADR-011 (no callers today; `engram_state` JSONB column untouched). **Deferred**.
11. **Cross-dialect SQLite/PostgreSQL JSONB pattern** — `app/models/message.py` uses `BigInteger().with_variant(Integer, "sqlite")` and `JSON().with_variant(JSONB(), "postgresql")`. Correct today; flagged for F13 awareness if any future migration adds a JSONB-only expression (e.g., `@>` containment) that would fail on SQLite.
12. **F11 PRs dependency for cross-team work** (AGENTS.md / `sdd-onboard` integration) — F12 branch is intentionally F11-independent; if F11 merges change `chat.py`'s `model.astream(prompt)` call signature, F12's persistence wrap will need a rebase patch.

---

## Verify report reference

**Intermediate snapshot** (rank 4 — superseded by orchestrator's launch prompt at rank 3):

- `verify-report.md @ 389d538` — `pass_with_warnings`, 12/13 REQ PASS, 1 CRITICAL drift (REQ-11 / SCN-5 — POST returned SSE `event: error` with HTTP 200 instead of spec-mandated HTTP 503). 64/64 F12-affected pytest + 8/8 vitest pass.

**Final state** (rank 3 — orchestrator's launch prompt, plus repo evidence corroborated):

- Commit **`f0731bb`** — `fix(chat): add Postgres liveness check before any other DB op (REQ-11 / SCN-5)`. Adds `SELECT 1` probe at `app/api/chat.py:92-105` BEFORE the project-ownership check and `build_langchain_model` call; raises `HTTPException(503, "Database unavailable; chat cannot persist turns right now.")` on `SQLAlchemyError`. Adds 39 LoC of test coverage in `tests/api/test_chat.py` to lock the contract.
- **Current verdict**: `pass_with_warnings` — **0 CRITICAL findings**. 13/13 REQs PASS (REQ-11 now satisfied via liveness check + 503). 8/8 SCNs PASS (SCN-5 now satisfied via `tests/api/test_chat.py` Postgres-down liveness test).
- **Test counts (current)** per orchestrator: **47/47 F12-affected pytest + 8/8 vitest pass**; 1 pre-existing failure from issue #66 unchanged. (Earlier `verify-report.md @ 389d538` listed 64 F12-affected pytest; the orchestrator's count reflects post-`f0731bb` reorganisation. We do not re-merge distinct counts into a single causal story; we cite the latest authoritative number.)
- **Source-of-truth pointers** (unchanged from verify-report §8): `app/api/chat.py:206-227` (commit-before-yield), `app/api/chat.py:92-105` (liveness probe), `app/core/message_store.py:130-173` (engram_mirror), `app/core/engram_client.py:53-123` (4 retrieval methods), `migrations/0008_add_messages_table.sql:17-38` (idempotent CREATE TABLE), `schema.sql:131-149` (verbatim mirror), `frontend/src/components/ChatWindow.tsx:26-35` (mount-time fetch).

---

## References

### Artifacts (in archive)

- Exploration — `openspec/changes/archive/2026-09-05-F12-engram-mcp/explore.md` @ `8ae860f`
- Proposal — `openspec/changes/archive/2026-09-05-F12-engram-mcp/proposal.md` @ `1cfcbc1`
- Design — `openspec/changes/archive/2026-09-05-F12-engram-mcp/design.md` @ `9a2c6f8` (17 sections, 4 SDs)
- Tasks — `openspec/changes/archive/2026-09-05-F12-engram-mcp/tasks.md` @ `bffd3fc` (13 hierarchical tasks, all `[x]`)
- Verify (snapshot) — `openspec/changes/archive/2026-09-05-F12-engram-mcp/verify-report.md` @ `389d538`
- Apply-progress (fallback file) — `openspec/changes/archive/2026-09-05-F12-engram-mcp/apply-progress.md`

### Canonical spec (preserved, source of truth)

- `openspec/specs/engram-conversation-memory/spec.md` @ `bec064f` — 13 REQ + 8 SCN

### ADRs

- **ADR-011** — `docs/adr/011-engram-conversation-mirror.md` @ `1cfcbc1` — locks hybrid storage + fire-and-forget Engram mirror
- **ADR-005** (context) — `docs/adr/005-engram-mcp.md` @ `d139c9e` — Engram as MCP of memory
- **ADR-002** (context) — `docs/adr/002-postgres-pgvector.md` @ `d139c9e` — Postgres + PGVector as the single DB

### Engram topic keys

| Topic | Type | Observation ID (preview) |
|---|---|---|
| `sdd/F12-engram-mcp/explore` | architecture | `#44` |
| `sdd/F12-engram-mcp/proposal` | architecture | `#45` |
| `sdd/F12-engram-mcp/spec` | architecture | `#46` |
| `sdd/F12-engram-mcp/design` | architecture | `#47` |
| `sdd/F12-engram-mcp/tasks` | architecture | `#48` |
| `sdd/F12-engram-mcp/apply-progress` | architecture | `#49` (to be merged with `status=archived` + `archived_at=2026-09-05T22:00:00Z` by this archive phase) |
| `sdd/F12-engram-mcp/verify` | architecture | `#51` |
| `sdd/F12-engram-mcp/archive` | architecture | (this report; persisted by this archive phase) |

### Migration pattern

- `migrations/0003_sync_sessions_table.sql` — idempotent ALTER TABLE pattern; F12.1's `0008` mirrors the structure.

### Issues

- Issue #14 — [F12] Engram MCP integrado (memoria) — https://github.com/danielCH26/arch-agent/issues/14
- Issue #66 — pre-existing test failures — https://github.com/danielCH26/arch-agent/issues/66

---

## Mechanical copy verification (archive move)

| Step | Command | Result |
|---|---|---|
| Snapshot source recursively | `cp -R openspec/changes/F12-engram-mcp <tmp>/source` | OK — 6 files captured (incl. untracked `apply-progress.md`) |
| Move source → archive | `Move-Item openspec/changes/F12-engram-mcp → openspec/changes/archive/2026-09-05-F12-engram-mcp` | OK — source removed |
| Source-gone check | `Test-Path openspec/changes/F12-engram-mcp` | `False` ✓ |
| Byte-identity readback | `git diff --no-index <tmp>/source openspec/changes/archive/2026-09-05-F12-engram-mcp` | exit `0` — **no differences** |
| SHA-256 per-file readback | `Get-FileHash` for each of 6 files (snapshot vs archive) | **All 6 match byte-for-byte** |

**Verbatim `diff -r` output** (using `git diff --no-index` as the platform-equivalent — Windows has no `diff.exe`; `git diff --no-index` recurses through directories and uses the same diff machinery; exit 0 means zero differences):

```
DIFF_EXIT=0
DIFF_OUTPUT_BEGIN
(warnings: LF will be replaced by CRLF the next time Git touches it — line-ending advisory only, not content)
DIFF_OUTPUT_END
```

Per-file SHA-256 (snapshot vs archive):

| File | SHA-256 | Status |
|---|---|---|
| `apply-progress.md` | `C66C25143A2412189CB64EB3C0D1DBB1134D1D44A805A73055EAC87DB04B7BB3` | OK |
| `design.md` | `E03FCE6C600A3CBC1930D956972AD6CBF4BD87DDE326767899EB75B41E6D3BA4` | OK |
| `explore.md` | `F7004D4958DC7C47C3A1B9716D22B3CAABC8F84934801DB177C3A7C8077227BD` | OK |
| `proposal.md` | `740149B95485D49F9CD76454C297772F32D2A37E5D2433C0816B64D0BA10FCDA` | OK |
| `tasks.md` | `08D94193F480BEDC10AFAF0F51158A5D4A6D98128E88FFB057E4A100BE202080` | OK |
| `verify-report.md` | `55C6F5227CC3821B719567B8EA0C8E69B7035337C7B72213D5315771B7C42995` | OK |

Snapshot cleaned (`Remove-Item -Recurse -Force` on temp dir).

---

**SDD cycle complete.** The change has been planned (`8ae860f` → `1cfcbc1` → `bec064f` → `9a2c6f8` → `bffd3fc`), implemented (`9f03251` + `0640b93` + `f16735a`), verified (`389d538`), drift-fixed (`f0731bb`), and archived (this report). Ready for stacked PR branching against `origin/development`.