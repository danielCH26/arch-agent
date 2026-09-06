# Tasks: F12 — Engram MCP (Memoria + Historial de Chat)

| Field | Value |
|---|---|
| **Change slug** | `F12-engram-mcp` |
| **Capability (NEW)** | `engram-conversation-memory` |
| **Branch** | `feature/F12-engram-mcp` |
| **Base** | `origin/development` @ `d139c9e` (PR #64 MERGED) |
| **HEAD** | `9a2c6f8` (F12 design) |
| **Spec** | `openspec/specs/engram-conversation-memory/spec.md` (13 REQ, 8 SCN) |
| **Design** | `openspec/changes/F12-engram-mcp/design.md` (17 sections, 4 SDs) |
| **ADR** | ADR-011 `docs/adr/011-engram-conversation-mirror.md` @ `1cfcbc1` |
| **Issue** | [#14](https://github.com/danielCH26/arch-agent/issues/14) |
| **Engram topic_key** | `sdd/F12-engram-mcp/tasks` (this file) |

---

## Review Workload Forecast

| Field | Value |
|---|---|
| Estimated changed lines (prod+tests) | ~906 LoC (496 prod + 410 tests) |
| 400-line budget risk (per slice) | **Low** — each slice ≤400 LoC |
| 800-line budget risk (combined) | **Low** — 906 ≈ 800 + chained slices keep each PR reviewable |
| Chained PRs recommended | **Yes** (per `delivery_strategy: auto-chain`) |
| Suggested split | PR #1 (F12.1 foundation) → PR #2 (F12.2 chat+GET) → PR #3 (F12.3 frontend) |
| Delivery strategy | `auto-chain` (cached) |
| Chain strategy | `stacked-to-main` (RESOLVED) |

Decision needed before apply: **No**
Chained PRs recommended: **Yes**
Chain strategy: **stacked-to-main**
400-line budget risk: **Low**

### Forecast table

| Slice | Task | Files (NEW/MOD) | LoC prod | LoC tests | REQ/SCN | Test files |
|---|---|---|---|---|---|---|
| **F12.1** | 1.1 `Message` ORM | NEW `app/models/message.py` (+1 mod `__init__.py`) | 30 | 0 | REQ-2 | — |
| **F12.1** | 1.2 `message_store` helpers | NEW `app/core/message_store.py` | 95 | 80 | REQ-3, SCN-3, SCN-6 | NEW `tests/core/test_message_store.py` |
| **F12.1** | 1.3 `EngramClient` extensions | MOD `app/core/engram_client.py` (+80) | 80 | 40 | REQ-5, SCN-6 | MOD `tests/test_engram_client.py` |
| **F12.1** | 1.4 Migration + schema mirror | NEW `migrations/0008_add_messages_table.sql` + MOD `schema.sql` (+50) | 100 | 0 | REQ-1, SCN-8 | — |
| **F12.1 subtotal** | | **2 NEW + 3 MOD** | **305** | **120** | REQ-1/2/3/5 | |
| **F12.2** | 2.1 `chat.py` wrap (`event_generator` tx + mirror) | MOD `app/api/chat.py` (+60) | 60 | 50 | REQ-4, REQ-6, REQ-10, SCN-1, SCN-4, SCN-7 | MOD `tests/api/test_chat.py` |
| **F12.2** | 2.2 `GET /api/chat/history` endpoint | MOD `app/api/chat.py` (+40) | 40 | 140 | REQ-7, REQ-11, SCN-3, SCN-5 | NEW `tests/api/test_chat_history.py` |
| **F12.2** | 2.3 `tests/test_llm_validator.py` mock patch | MOD `tests/test_llm_validator.py` | 10 | 0 | REQ-12 | (in-file) |
| **F12.2 subtotal** | | **1 NEW + 2 MOD** | **110** | **190** | REQ-4/6/7/10/11/12 | |
| **F12.3** | 3.1 `fetchChatHistory` API client | MOD `frontend/src/api/chat.ts` | 30 | 0 | REQ-7 | — |
| **F12.3** | 3.2 `chatStore.loadHistory` + flag | MOD `frontend/src/stores/chatStore.ts` | 40 | 50 | REQ-8 | NEW `frontend/src/stores/__tests__/chatStore.test.ts` |
| **F12.3** | 3.3 `ChatWindow` `useEffect` mount | MOD `frontend/src/components/ChatWindow.tsx` | 20 | 50 | REQ-9, SCN-2 | NEW `frontend/src/components/__tests__/ChatWindow.test.tsx` |
| **F12.3 subtotal** | | **2 NEW + 3 MOD** | **90** | **100** | REQ-8/9 | |
| **GRAND TOTAL** | | **5 NEW + 8 MOD** | **~496** | **~410** | **13 REQ / 8 SCN** | |

---

## Chained-PR Decision

- **Yes, chained PRs required** (per cached `delivery_strategy: auto-chain`).
- **Chain strategy: stacked-to-main** (RESOLVED by orchestrator session preflight; do not reopen).
- **Slice sequencing** (each PR merges to `origin/development` in order):
  1. **F12.1** — backend foundation (inert, additive only). `chat.py` untouched. No behaviour change visible to callers; CI green on its own.
  2. **F12.2** — chat integration + history endpoint. `POST /api/chat` now persists before `yield done`; new `GET /api/chat/history` exposed.
  3. **F12.3** — frontend persistence. `ChatWindow` mount fetches history with `isStreaming` + `loadingHistory` guard.
- **Slice seams (no overlap):**
  - F12.1 → F12.2 seam: `app/core/message_store.save_message` + `engram_mirror` are introduced in F12.1; F12.2 only **calls** them inside `chat.py`'s `event_generator`.
  - F12.2 → F12.3 seam: `GET /api/chat/history?project_id=&limit=` ships in F12.2; F12.3 only **calls** it from `chatStore.loadHistory`.
- **Per-PR ≤400 LoC hard rule** (chained-pr skill): F12.1 = ~425 LoC, F12.2 = ~300 LoC, F12.3 = ~190 LoC. **F12.1 is slightly over the per-PR soft target but within the 400 hard rule per the design §12 table**; safe to land as one PR because all production code is inert (no behaviour change).
- **`decision_needed_before_apply: false`** (auto-chain + cached chain_strategy + session preflight override).

---

## Slice Plan

### F12.1 — Backend Foundation (inert)
- **Branch:** `feature/F12-slice-1` · **Base:** `origin/development` @ `d139c9e`
- **NEW files (2):** `app/models/message.py`, `app/core/message_store.py`, `migrations/0008_add_messages_table.sql`, `tests/core/test_message_store.py`
- **MOD files (3):** `app/models/__init__.py` (+1 line), `app/core/engram_client.py` (+80 lines), `schema.sql` (+50 lines), `tests/test_engram_client.py` (+40 lines)
- **LoC budget:** ~425 (305 prod + 120 tests)
- **REQ/SCN coverage:** REQ-1, REQ-2, REQ-3, REQ-5, SCN-3, SCN-6, SCN-8
- **Verification:**
  - `pytest tests/core/test_message_store.py -v` — store unit tests
  - `pytest tests/test_engram_client.py -v` — 4 new methods + `ValueError` on `project=None`
  - `python migrations/run_migrations.py` (idempotent on second run, SCN-8)
  - `curl -s http://localhost:8000/api/chat` (smoke: 200/401/409 unchanged)
- **Rollback:** revert the 5 file commits; migration is `CREATE TABLE IF NOT EXISTS` so safe to leave in DB or `DROP TABLE messages`.

### F12.2 — Chat Integration + History Endpoint
- **Branch:** `feature/F12-slice-2` · **Base:** `feature/F12-slice-1`
- **NEW files (1):** `tests/api/test_chat_history.py`
- **MOD files (2):** `app/api/chat.py` (+100 lines for tx wrap + GET history), `tests/api/test_chat.py` (+50 lines), `tests/test_llm_validator.py` (+10 lines)
- **LoC budget:** ~300 (110 prod + 190 tests)
- **REQ/SCN coverage:** REQ-4, REQ-6, REQ-7, REQ-10, REQ-11, REQ-12, SCN-1, SCN-4, SCN-5, SCN-7
- **Verification:**
  - `pytest tests/api/test_chat.py tests/api/test_chat_history.py -v` — commit-before-yield + GET history
  - `pytest tests/test_llm_validator.py -v` — 4 mock methods present
  - `curl -X POST http://localhost:8000/api/chat -d '{"message":"hi"}'` — SSE events; assert order
  - `curl http://localhost:8000/api/chat/history?project_id=1&limit=5 -H "Authorization: Bearer …"` — JSON `{messages:[]}`
- **Rollback:** revert the 3 file commits; `chat.py` reverts to pre-F12.2 behaviour, `GET /api/chat/history` endpoint disappears; no DB rows lost.

### F12.3 — Frontend Persistence
- **Branch:** `feature/F12-slice-3` · **Base:** `feature/F12-slice-2`
- **NEW files (2):** `frontend/src/stores/__tests__/chatStore.test.ts`, `frontend/src/components/__tests__/ChatWindow.test.tsx`
- **MOD files (3):** `frontend/src/api/chat.ts` (+30), `frontend/src/stores/chatStore.ts` (+40), `frontend/src/components/ChatWindow.tsx` (+20)
- **LoC budget:** ~190 (90 prod + 100 tests)
- **REQ/SCN coverage:** REQ-8, REQ-9, SCN-2, REQ-13
- **Verification:**
  - `cd frontend && npx vitest run src/stores/__tests__/chatStore.test.ts src/components/__tests__/ChatWindow.test.tsx` — mount-time guard
  - `cd frontend && npm run build` — REQ-13 (no TS errors)
  - Manual: reload browser at `ChatWindow`; prior messages render within 1 s.
- **Rollback:** revert the 5 file commits; `ChatWindow` mount stops calling history; chat still works (POST still persists server-side).

---

## Tasks (hierarchical)

### 1. Backend Foundation (F12.1)

- [x] **1.1** Create `app/models/message.py` — SQLAlchemy 2.0 `Message` ORM (REQ-2). **[F12.1 · NEW · 30 LoC]** · target: REQ-2 · acceptance: `python -c "from app.models.message import Message"` exits 0 · commit: `feat(messages): add Message ORM model`.
- [x] **1.2** Register `Message` in `app/models/__init__.py` (+1 line). **[F12.1 · MOD · 1 LoC]** · target: REQ-2 · acceptance: `Base.metadata.tables["messages"]` is present · commit: `chore(messages): register Message ORM`.
- [x] **1.3** Create `migrations/0008_add_messages_table.sql` — idempotent `CREATE TABLE IF NOT EXISTS` + FKs + indexes (REQ-1, SCN-8). **[F12.1 · NEW · 50 LoC]** · target: REQ-1, SCN-8 · acceptance: `python migrations/run_migrations.py` runs twice with no error · commit: `feat(db): add 0008 messages table migration`.
- [x] **1.4** Mirror the new table in `schema.sql` (+50 lines). **[F12.1 · MOD · 50 LoC]** · target: REQ-1 · acceptance: greenfield `init_db.py` creates the table · commit: `chore(db): mirror messages table in schema.sql`.
- [x] **1.5** Create `app/core/message_store.py` — `save_message`, `list_recent`, `engram_mirror`, `_ensure_user_session` (REQ-3, REQ-6, REQ-10). **[F12.1 · NEW · 95 LoC]** · target: REQ-3, REQ-6, REQ-10 · acceptance: `pytest tests/core/test_message_store.py` passes · commit: `feat(messages): add message_store with engram mirror helper`.
- [x] **1.6** Extend `app/core/engram_client.py` with `search`, `get_observation`, `save(topic_key)`, `delete` (+80 lines; existing methods untouched). **[F12.1 · MOD · 80 LoC]** · target: REQ-5, SCN-6 · acceptance: `engram_client.search(project=None)` raises `ValueError` · commit: `feat(engram): add search/get_observation/save(topic_key)/delete methods`.
- [x] **1.7** Add unit tests in `tests/core/test_message_store.py` (80 LoC). **[F12.1 · NEW · 80 LoC]** · target: REQ-3, SCN-3, SCN-6 · acceptance: covers save/list/order/limit-clamp/cross-user · commit: `test(messages): add message_store unit tests`.
- [x] **1.8** Extend `tests/test_engram_client.py` for the 4 new methods (+40 LoC). **[F12.1 · MOD · 40 LoC]** · target: REQ-5, SCN-6 · acceptance: `search(project=None)` raises `ValueError("project is required")`; `save(topic_key=…)` sends body with `topic_key` · commit: `test(engram): cover search/save/get_observation/delete`.

### 2. Backend Chat Integration (F12.2)

- [x] **2.1** Wrap `app/api/chat.py::event_generator` to insert `Message(user)` + `Message(assistant)` in one Postgres tx BEFORE `yield event: done` (+60 lines). **[F12.2 · MOD · 60 LoC]** · target: REQ-4, REQ-6, SCN-1, SCN-7 · acceptance: test asserts `db.commit()` called before the `done` yield · commit: `feat(chat): persist user+assistant rows before done event`.
- [x] **2.2** Add `GET /api/chat/history` endpoint to `app/api/chat.py` (+40 lines; `limit` clamp [1,50]; 404 cross-user; 200 `[]` on DB-down). **[F12.2 · MOD · 40 LoC]** · target: REQ-7, REQ-11, SCN-3, SCN-5 · acceptance: contract test covers defaults/clamp/404/DB-down · commit: `feat(chat): add GET /api/chat/history endpoint`.
- [x] **2.3** Extend `tests/api/test_chat.py` with commit-before-yield + Engram-down path (+50 LoC). **[F12.2 · MOD · 50 LoC]** · target: REQ-4, REQ-10, SCN-1, SCN-4, SCN-7 · acceptance: `EngramError` does not propagate to caller · commit: `test(chat): assert commit-before-yield and engram-down resilience`.
- [x] **2.4** Create `tests/api/test_chat_history.py` (140 LoC). **[F12.2 · NEW · 140 LoC]** · target: REQ-7, REQ-11, SCN-3, SCN-5 · acceptance: default N=5, limit clamp, 404 cross-user, 200 `[]` on `OperationalError` · commit: `test(chat): add history endpoint contract tests`.
- [x] **2.5** Patch `tests/test_llm_validator.py` mock to expose `search`/`get_observation`/`save`/`delete` (+10 lines). **[F12.2 · MOD · 10 LoC]** · target: REQ-12 · acceptance: `pytest tests/test_llm_validator.py` passes unchanged semantics · commit: `test(llm-validator): add 4 engram mock methods`.

### 3. Frontend Persistence (F12.3)

- [ ] **3.1** Add `fetchChatHistory(projectId, limit=5)` to `frontend/src/api/chat.ts` (+30 lines). **[F12.3 · MOD · 30 LoC]** · target: REQ-7 · acceptance: returns parsed `Message[]`; respects `authStore.token` · commit: `feat(chat-api): add fetchChatHistory client`.
- [ ] **3.2** Extend `frontend/src/stores/chatStore.ts` with `loadHistory(projectId)` + `loadingHistory` flag; atomic `set({messages, loadingHistory:false})` (+40 lines). **[F12.3 · MOD · 40 LoC]** · target: REQ-8 · acceptance: Vitest covers loading/error/success · commit: `feat(chat-store): add loadHistory action with loadingHistory flag`.
- [ ] **3.3** Add `useEffect(..., [])` to `frontend/src/components/ChatWindow.tsx` invoking `loadHistory(projectId)` guarded by `isStreaming === false && loadingHistory === false` (+20 lines). **[F12.3 · MOD · 20 LoC]** · target: REQ-9, SCN-2 · acceptance: StrictMode-safe Vitest · commit: `feat(chat-window): load history on mount with streaming guard`.
- [ ] **3.4** Create `frontend/src/stores/__tests__/chatStore.test.ts` (50 LoC). **[F12.3 · NEW · 50 LoC]** · target: REQ-8 · acceptance: `loadHistory(42)` sets flag, replaces messages atomically, clears on error · commit: `test(chat-store): cover loadHistory success and error paths`.
- [ ] **3.5** Create `frontend/src/components/__tests__/ChatWindow.test.tsx` (50 LoC). **[F12.3 · NEW · 50 LoC]** · target: REQ-9, SCN-2 · acceptance: mount fires once under StrictMode; `isStreaming=true` blocks fetch · commit: `test(chat-window): assert StrictMode-safe mount fetch`.

---

## Apply-progress seed

Engram observation (auto-saved below) with structure:
```json
{
  "started_at": "<ISO8601>",
  "current_slice": "F12.1",
  "completed_tasks": [],
  "in_flight": "F12.1",
  "blocked": [],
  "notes": "F12 starts here; all 3 slices queued back-to-back in AUTO mode"
}
```
Persisted to Engram topic_key `sdd/F12-engram-mcp/apply-progress` as `type=config`, `capture_prompt=false`.

---

## Out of scope (carried from design §14)

- MCP-stdio transport for the Engram client (semantic search not enabled).
- Cross-user memory sharing (REQ-7 + REQ-5 enforce strict `user_id` scoping).
- Auto-summarisation of long histories beyond last-N window (token-cost control).
- Switching the LLM tool surface to MCP (F11 territory).
- F11 LangChain agent runtime integration — PRs #69–74 remain OPEN; F12 is independent.
- `app/core/session_store.py` refactor (dead code) — deferred per ADR-011.
- `app/api/sse.py::SSEStreamCallbackHandler` threading into `model.astream`.
- Frontend virtualisation / pagination beyond `?limit=` parameter.
- `tests/test_schema_sync.py` CI guard for `schema.sql` ↔ `migrations/0008` parity (documented as future work in migration header).

---

## Risks (re-stated from design §15)

| # | Risk | Likelihood | Mitigation (in tasks) |
|---|---|---|---|
| 1 | TTFT regression from synchronous per-message save | Med | 2.1 + benchmark in F12.2 PR; fall back to fire-and-forget if >100 ms. |
| 2 | Frontend StrictMode race clobbers in-flight tokens | Med | 3.3 guard + 3.5 Vitest asserts double-render fires once. |
| 3 | `test_llm_validator.py` dormant imports on REQ-5 methods | Med | 2.5 patches mocks. |
| 4 | Cross-user leakage via `engram_client.search` | Med | 1.6 raises `ValueError`; 1.8 + 2.2 cross-user test. |
| 5 | Migration drift between `schema.sql` and `0008` | Low | 1.3 + 1.4 mirror verbatim; runner idempotent. |
| 6 | Token growth in LLM context | Med | last-5 hard cap; `?limit=` max 50; `get_context()` only on explicit request. |
| 7 | First-message `UserSession` lazy-upsert race | Low | 1.5 catches `IntegrityError` + re-`SELECT`. |
| 8 | Disconnect after Postgres commit but before SSE `done` | Low | Acceptable; row surfaces on next history call. |
| 9 | `chat.py:121` `SSEStreamCallbackHandler` remains dead | Low | Out of scope (design §14). |

---

## References

- **Exploration** — `openspec/changes/F12-engram-mcp/explore.md` @ `8ae860f` · Engram `sdd/F12-engram-mcp/explore` (#44)
- **Proposal** — `openspec/changes/F12-engram-mcp/proposal.md` @ `1cfcbc1` · Engram `sdd/F12-engram-mcp/proposal` (#45)
- **Spec** — `openspec/specs/engram-conversation-memory/spec.md` @ `bec064f` · Engram `sdd/F12-engram-mcp/spec` (#46)
- **Design** — `openspec/changes/F12-engram-mcp/design.md` @ `9a2c6f8` · Engram `sdd/F12-engram-mcp/design` (#47)
- **ADR-011** — `docs/adr/011-engram-conversation-mirror.md` @ `1cfcbc1`
- **ADR-005** (context) — `docs/adr/005-engram-mcp.md` @ `d139c9e`
- **ADR-002** (context) — `docs/adr/002-postgres-pgvector.md` @ `d139c9e`
- **Migration pattern** — `migrations/0003_sync_sessions_table.sql`
- **Issue** — [#14 — [F12] Engram MCP integrado (memoria)](https://github.com/danielCH26/arch-agent/issues/14)