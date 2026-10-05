# Proposal: F12 — Engram MCP (Memoria + Historial de Chat)

**Slug:** `F12-engram-mcp` &nbsp;&nbsp; **Branch:** `feature/F12-engram-mcp` &nbsp;&nbsp; **Base:** `origin/development @ d139c9e` &nbsp;&nbsp; **HEAD:** `8ae860f`
**Capability (NEW):** `engram-conversation-memory` → `openspec/specs/engram-conversation-memory/spec.md`
**Relationship:** Extends [explore.md](explore.md) (`8ae860f`) and [ADR-005](../docs/adr/005-engram-mcp.md) (`d139c9e`).
**Issue:** [#14 — [F12] Engram MCP integrado (memoria)](https://github.com/danielCH26/arch-agent/issues/14) (OPEN; sprint-2).
**Engram topic_key:** `sdd/F12-engram-mcp/proposal` (this file).

---

## 1. Why

Issue #14 commits F12 to deliver two distinct memory surfaces: **team-facing architectural memory** (decisions, context, conventions persisted across sessions for the whole team — already partially framed by ADR-005) and **user-facing chat history** (every `user` + `assistant` message persisted so a page reload lands the user exactly where they left off). Today both surfaces are absent: `app/api/chat.py:155-188` ends the SSE stream with zero persistence, `frontend/src/stores/chatStore.ts:29` initialises `messages=[]` on every reload, and `EngramClient` only writes — never reads. F12 closes that gap.

## 2. What changes

**Backend** — new `Message` ORM (`app/models/message.py`) + new helper `app/core/message_store.py`; extend `EngramClient` with `search`/`get_observation`/`save(topic_key)`/`delete` (the methods `tests/test_llm_validator.py:170,178,197,223` already anticipate); refactor `app/api/chat.py:155-188` to insert both `Message` rows (user + assistant) in a single Postgres transaction *before* `yield event: done`; new endpoint `GET /api/chat/history?project_id=&limit=5` returning the last-N turns ordered ASC.
**Frontend** — new `loadHistory(projectId)` action in `frontend/src/stores/chatStore.ts`; `ChatWindow.tsx` `useEffect(..., [])` invokes it on mount with a `loadingHistory` flag and an `isStreaming` guard to avoid clobbering in-flight tokens.
**Migrations** — new `migrations/0008_add_messages_table.sql` (id, user_id, project_id NULL, role, content, sources_json, engram_observation_id NULL, created_at + indexes) + mirrored CREATE TABLE in `schema.sql` for greenfield DBs.
**ADRs** — new ADR-011 "Engram as conversation-history mirror"; ADR-012 "session_id scope = per-(user, project)" (optional; the session-id scope is small enough to live inside the proposal).
**Tests** — unit tests for `message_store`, contract tests for the extended `EngramClient`, integration test for `GET /api/chat/history`; Vitest for `loadHistory` + mount-time guard.

## 3. Approach chosen — Hybrid (Postgres = truth, Engram = sibling)

Postgres `messages` table is the **source of truth** for chat turns (queryable, ACID, FTS-ready, no coupling to Engram availability). Engram receives a **parallel `save_observation` mirror** for semantic recall (`get_context(project)` already aggregates; F12 does not need a new endpoint to read). Architectural decisions continue to flow to Engram unchanged (ADR-005 stays valid). Chat history is the most-visible user-facing layer; architectural decisions are the most-visible team-facing layer. Hybrid honours both.

## 4. Out of scope (v1)

MCP-stdio transport; cross-user memory sharing; auto-summarization of long histories beyond the last-N window; switching the LLM tool surface to MCP; F11-style LangChain agent runtime (F11 PRs #69–74 still OPEN, not merged — F12 plans against the `d139c9e` baseline and does not depend on them).

## 5. Capabilities

### New Capabilities
- `engram-conversation-memory`: Persists `user` and `assistant` chat turns to Postgres (`messages` table) as source of truth and mirrors them to Engram as observations for semantic recall. Exposes `GET /api/chat/history?project_id=&limit=` for retrieval; folds last-N verbatim into the LLM prompt and degrades gracefully when Engram is unreachable.

### Modified Capabilities
- None at the spec level. `app/api/chat.py` is implementation, not spec. If a `chat-api` capability is later introduced in `openspec/specs/`, it gets a delta spec.

## 6. Resolved ambiguities

| # | Question | Decision | Rationale (1 line) |
|---|----------|----------|--------------------|
| 1 | Storage choice | **Hybrid** — Postgres = truth, Engram = sibling | Engram v2 HTTP has no list-by-session endpoint (§2.2 explore), and ADR-005 already names Engram as the memory substrate — honour both. |
| 2 | Persistence cadence | **Synchronous per-turn, single transaction, BEFORE `yield done`** | Mitigates risk #1 (disconnect mid-stream losing assistant row) and keeps TTFT impact ≤50ms (local socket). |
| 3 | Retrieval strategy | **Last N verbatim, default N=5 turns, `?limit=` override** | Cheapest, chronological, predictable token cost; Engram `get_context()` digest remains available for explicit long-range recall. |
| 4 | session_id scope | **per-(user, project)** with deterministic `arch-agent-user-{user_id}-project-{project_id}-chat` | Mirrors existing project-scoped chat data model; scopes future list-by-session queries; aligns with ADR-005 per-user isolation. |
| 5 | Frontend load | **`useEffect` on mount, single fetch, `loadingHistory` + `isStreaming` guards** | Simplest, matches the existing mount-once pattern; StrictMode-safe with the streaming guard. |
| 6 | Schema strategy | **New `messages` table** with role enum (`user`/`assistant`/`system`), FK to `users` + `projects`, JSONB `sources_json`, nullable `engram_observation_id` for cross-reference | Mirrors the `sessions` / `engram_state` precedent (`migrations/0003_sync_sessions_table.sql`); keeps the Engram mirror traceable. |
| 7 | LLM prompt composition | **Fold last-5 turns verbatim into the user-message stream**; do **not** auto-inject `get_context()` digest | Token budget stays bounded; long-range recall available on explicit user request. |
| 8 | Failure mode | **Postgres up + Engram down → chat works, history loads, observation mirror logs + drops**; **Both down → 503 on write, GET history returns `200 []`** | Chat is user-critical (loud 503 acceptable when truly nothing works); persistence is best-effort. |

## 7. Affected components (paths pinned to HEAD `8ae860f`)

| Path | Impact | Purpose |
|------|--------|---------|
| `app/models/message.py` | NEW | SQLAlchemy `Message` ORM (id, user_id, project_id, role, content, sources_json, engram_observation_id, created_at). |
| `app/core/message_store.py` | NEW | `insert_message(...)`, `list_recent(user_id, project_id, limit)`, `engram_mirror(...)` — Postgres write + fire-and-forget Engram mirror. |
| `app/core/engram_client.py` | MODIFIED | Add `search`, `get_observation`, `save(topic_key=…)`, `delete` — matches what `tests/test_llm_validator.py` already calls. |
| `app/api/chat.py` | MODIFIED | Insert both `Message` rows in one transaction before `yield event: done` (line 186); add `GET /api/chat/history` endpoint. |
| `app/api/dependencies.py` | MODIFIED (if needed) | Add `get_message_store` dependency. |
| `app/models/__init__.py` | MODIFIED | Register `Message` in SQLAlchemy `Base.metadata`. |
| `migrations/0008_add_messages_table.sql` | NEW | CREATE TABLE + indexes (user_id, project_id, created_at DESC). |
| `schema.sql` | MODIFIED | Mirror the CREATE TABLE block (greenfield DB parity). |
| `tests/core/test_message_store.py` | NEW | Unit tests for the store. |
| `tests/api/test_chat_history.py` | NEW | Contract test for `GET /api/chat/history`. |
| `tests/test_engram_client.py` | MODIFIED | Cover the four new `EngramClient` methods. |
| `tests/test_llm_validator.py` | MODIFIED | Update mocks to match the new method signatures. |
| `frontend/src/stores/chatStore.ts` | MODIFIED | Add `loadHistory(projectId)` action + `loadingHistory` flag + `isStreaming` guard. |
| `frontend/src/api/chat.ts` | MODIFIED | Add `fetchChatHistory(projectId, limit)` API client. |
| `frontend/src/components/ChatWindow.tsx` | MODIFIED | `useEffect(..., [])` calls `loadHistory` on mount. |
| `frontend/src/components/ChatWindow.test.tsx` | NEW (or extended) | Vitest for mount-time fetch + StrictMode guard. |
| `docs/adr/011-engram-conversation-mirror.md` | NEW | Locks the hybrid storage + fire-and-forget Engram mirror pattern. |

## 8. Stack dependency

- **PR #64 (RAG + PGVector) — MERGED at `d139c9e`.** F12 builds on the merged base.
- **F11 PRs #69–74 (LangChain agent runtime + Context7 MCP + Langfuse) — OPEN, NOT merged.** F12 is **independent** of F11; `chat.py` still calls `model.astream(prompt)` directly, so the persistence layer slots in between the model and the SSE stream without awaiting F11.
- **Engram runtime** — container `engram` + `engram-proxy` socat live at `d139c9e` (`docker-compose.yml`); `ENGRAM_URL` env wired in `app/core/engram_client.py:17`.

## 9. Success criteria

Mapped to the 5 issue ACs:

1. **Decisiones se guardan automáticamente** → Given the agent emits an architectural decision, When the chat turn completes, Then an Engram observation of `type=decision` exists for `(user_id, project_id)` AND the equivalent `Message(role=assistant, sources_json)` row exists in Postgres.
2. **El agente recupera contexto relevante** → Given at least 3 prior decisions in Engram for the project, When `chat.py` builds the prompt, Then the last 5 turns are folded in verbatim AND `engram_client.get_context(project)` is available as a future opt-in.
3. **Persistencia entre sesiones** → Given the user reloads the browser, When `ChatWindow` mounts, Then the previous turns (≤ N=5 by default, `?limit=` overrides) are visible from `GET /api/chat/history`.
4. **Al recargar la página, los mensajes previos del chat siguen visibles** → Same as #3 with a Vitest assertion on `chatStore.messages.length > 0` after mount.
5. **El usuario puede seguir desde donde dejó la conversación** → Given the user sends a follow-up message, When the request completes, Then both rows appear in the next `GET /api/chat/history` call (chronological).

Plus negative criteria:

- **Engram unreachable + Postgres up** → `GET /api/chat/history` returns 200 with the persisted rows; the Engram mirror logs and drops without affecting the user.
- **Both stores unreachable** → POST chat returns 503; GET history returns 200 `[]`.
- **No `Message` regression on existing tests** → `tests/api/test_chat.py` keeps passing; `tests/test_engram_validator.py` mocks updated for the four new methods.

## 10. Risks and mitigations

| # | Risk | Likelihood | Mitigation |
|---|------|------------|------------|
| 1 | Disconnect mid-stream loses assistant row | Med | Insert both rows in single Postgres transaction BEFORE `yield done`. |
| 2 | Engram v2 HTTP lacks list-by-session | Confirmed | Pure-Engram retrieval rejected; Hybrid stores canon in Postgres. |
| 3 | Cross-user memory leakage via Engram `search` | Med | All Engram calls scope by `project` AND include `user_id` in observation `title`; tests assert filter presence. |
| 4 | `session_store.py` dead code | Low | F12 does not refactor it; documented in ADR-011 as deferred. |
| 5 | SSE handler half-wired (`chat.py:121`) | Low | F12 either threads the handler into `model.astream` for clean token collection, or removes the dead construct; tests unchanged. |
| 6 | Zustand hydration under StrictMode | Med | `loadHistory` guards on `isStreaming === false` before mutating `messages`. |
| 7 | Migration hygiene (`schema.sql` vs `migrations/`) | Low | Mirror the CREATE TABLE in `schema.sql` exactly as in `0008`; `run_migrations.py` already applies both. |
| 8 | Token growth in LLM context | Med | Hard cap N=5 turns; `?limit=` override; `get_context()` injection only on explicit request. |
| 9 | `tests/test_llm_validator.py` dormant imports | Med | Update mocks for the four new `EngramClient` methods (signatures: `search(query, limit)`, `get_observation(id)`, `save(topic_key, content, title, type)`, `delete(topic_key)`). |
| 10 | TTFT regression from synchronous per-turn save | Low–Med | Local socket round-trip ≤50ms; benchmark in F12.2 PR; fall back to fire-and-forget if TTFT regresses >100ms. |

## 11. Rollback plan

1. **Drop the migration** — `migrations/0008_add_messages_table.sql` is reversible (DROP TABLE messages); `schema.sql` reverts to its prior version on the same commit.
2. **Drop the chat.py persistence calls** — remove the pre-`yield done` transaction block + `engram_mirror` call. `GET /api/chat/history` endpoint can stay (returns empty) or be removed; either is safe.
3. **Drop the frontend `loadHistory` action + `useEffect`** — `chatStore.ts` reverts to `messages: []`; `ChatWindow.tsx` reverts to mount-without-fetch. Behaviour returns to the d139c9e baseline.
4. **Engram client extensions are additive** — `search`/`get_observation`/`save(topic_key)`/`delete` do not change existing behaviour; can stay after rollback without risk.
5. **No DB data loss** — rollback never deletes rows that already exist (the `messages` table can be kept for forensic value or dropped; either is non-destructive to other tables).

## 12. Delivery plan (chained PRs)

F12 is backend-heavy + a small frontend slice; forecast ≈800–1100 LoC across `app/models/message.py`, `app/core/message_store.py`, `app/core/engram_client.py`, `app/api/chat.py`, migrations, tests, plus ~150 LoC frontend. **At the 800-line review budget** this is on the edge of single-PR; safe forecast ≤1500 LoC total. **Chained slices recommended** (chained-pr skill: split when forecast >400 LoC and slices can land independently).

Forecast slices:

- **F12.1 — Backend foundation** (≈350 LoC) — `Message` model + `message_store` + `EngramClient` extensions + migration `0008` + `schema.sql` mirror + unit tests. No `chat.py` change yet. CI green on its own. Dependency for F12.2.
- **F12.2 — Chat integration + history endpoint** (≈400 LoC) — `chat.py` post-stream save + `GET /api/chat/history` + integration tests + `tests/test_llm_validator.py` mock updates + ADR-011. Depends on F12.1. Behaviour-preserving for non-persistence callers.
- **F12.3 — Frontend persistence** (≈150 LoC) — `chatStore.loadHistory` + `ChatWindow.tsx` `useEffect` + `api/chat.ts` `fetchChatHistory` + Vitest. Depends on F12.2 endpoint. Smallest slice; can land after F12.2 is reviewed.

Decision deferred to `sdd-tasks` for the exact line counts and re-slice boundary.

## 13. ADRs to add

- **ADR-011 — Engram as conversation-history mirror** (MANDATORY). Locks: (a) Postgres `messages` is the source of truth; (b) Engram receives a fire-and-forget `save_observation` mirror with `engram_observation_id` cross-reference; (c) graceful degradation when Engram is down; (d) retrieval via Postgres `SELECT ... ORDER BY created_at DESC LIMIT N`. Path: `docs/adr/011-engram-conversation-mirror.md`.
- **ADR-012 — `session_id` scope = per-(user, project)** (OPTIONAL). Small enough to live in proposal §6 row 4; promote to its own ADR only if a future change to scope wants a paper trail. Defer.

## 14. References

- [explore.md](explore.md) (`8ae860f`) — 9 risks, 3 alternatives, Engram v2.0.0-rc.6 endpoint probe results.
- [ADR-005](../docs/adr/005-engram-mcp.md) (`d139c9e`) — Engram as MCP of memory; rationale + consequences.
- [Issue #14](https://github.com/danielCH26/arch-agent/issues/14) — Original scope + chat-history extension (orchestrator-supplied).
- [ADR-002](../docs/adr/002-postgres-pgvector.md) — Postgres + PGVector as the single DB; F12's `messages` table rides on the same Postgres instance.
- [Migration 0003](../migrations/0003_sync_sessions_table.sql) — Idempotent ALTER TABLE pattern; F12.1's `0008` mirrors the structure.
