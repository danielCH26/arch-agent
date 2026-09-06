# Engram Conversation Memory — Specification

**Capability folder:** `openspec/specs/engram-conversation-memory/`
**Branch:** `feature/F12-engram-mcp` · **Base:** `origin/development` @ d139c9e (PR #64 merged)
**Source proposal:** `openspec/changes/F12-engram-mcp/proposal.md` @ 1cfcbc1 · Engram #45
**Source exploration:** `openspec/changes/F12-engram-mcp/explore.md` @ 8ae860f · Engram #44
**ADR:** ADR-011 (`docs/adr/011-engram-conversation-mirror.md`) at 1cfcbc1; context ADR-005
**Engram topic_key:** `sdd/F12-engram-mcp/spec`
**Issue:** [danielCH26/arch-agent#14](https://github.com/danielCH26/arch-agent/issues/14) — [F12] Engram MCP integrado (memoria)
**Capability choice:** This is a NEW capability; the folder path `engram-conversation-memory` documents the choice in lieu of a more generic name (e.g. `chat-history`) so the two memory surfaces in Issue #14 — team decisions and chat history — share one spec while their requirements stay independently testable.

## Purpose

Persist every chat turn (user + assistant) so a user resumes exactly where they left off after a page reload, while mirroring each turn into Engram for cross-session semantic recall. Postgres `messages` is the canonical store; Engram receives fire-and-forget sibling observations. Either store degrades gracefully when the other is unavailable. Architectural decisions follow the same Engram channel as observations.

## Requirements

### REQ-1 — Messages table schema
The system MUST add a Postgres `messages` table via `migrations/0008_add_messages_table.sql` AND mirror it verbatim in `schema.sql`. Columns MUST be `id BIGSERIAL PK, session_id INT NOT NULL, project_id INT NULL, user_id INT NOT NULL, role TEXT NOT NULL CHECK (role IN ('user','assistant','system')), content TEXT NOT NULL, citations JSONB NOT NULL DEFAULT '[]', engram_observation_id BIGINT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now()`. FKs MUST be `session_id → sessions(id) ON DELETE CASCADE`, `project_id → projects(id) ON DELETE SET NULL`, `user_id → users(id) ON DELETE CASCADE`. Migration MUST be idempotent (`CREATE TABLE IF NOT EXISTS`).

### REQ-2 — Message ORM model
`app/models/message.py` MUST expose a SQLAlchemy 2.0 `Message` ORM mapping REQ-1 columns. `app/models/__init__.py` MUST register it.

### REQ-3 — Message store helpers
`app/core/message_store.py` MUST expose `save_message(db, session_id, project_id, user_id, role, content, citations=None) -> Message` and `list_recent(db, session_id, limit=5) -> list[Message]`. `list_recent` MUST order by `created_at DESC, id DESC`.

### REQ-4 — Synchronous per-turn save before SSE `done`
`POST /api/chat` MUST call `save_message` for the user message AND for the assembled assistant response inside a single Postgres transaction that commits BEFORE the SSE handler yields `event: done`.

### REQ-5 — Engram client retrieval methods
`app/core/engram_client.py` MUST be extended with `search(scope, query, project, user_id)`, `get_observation(observation_id)`, `save(topic_key, content, ...)`, and `delete(observation_id)`. Each call MUST scope by `project` and `user_id`. `search` MUST raise `ValueError` when `project` is missing.

### REQ-6 — Fire-and-forget Engram mirror
After the REQ-4 transaction commits, the chat route MUST fire-and-forget `engram_client.save(topic_key=..., content=...)` for the user message AND for the assistant response. Failures MUST log WARNING and MUST NOT propagate to the caller or the SSE stream.

### REQ-7 — History endpoint
`GET /api/chat/history?project_id=<int>&limit=<int>` MUST return JSON `{messages: [{role, content, citations, created_at}, ...]}` ordered newest-first. `limit` defaults to 5 and MUST be clamped to `[1, 50]`. The endpoint MUST scope by the authenticated `user_id` and `project_id`; cross-user access MUST return 404.

### REQ-8 — Frontend history action
`frontend/src/stores/chatStore.ts` MUST expose `loadHistory(projectId)` that calls REQ-7 and replaces `messages` atomically. While in-flight the action MUST set `loadingHistory=true`; on success it MUST `set({messages, loadingHistory: false})`; on error it MUST clear `loadingHistory` and leave `messages` untouched.

### REQ-9 — Mount-time fetch with StrictMode guard
`frontend/src/components/ChatWindow.tsx` MUST invoke `chatStore.loadHistory(projectId)` from a `useEffect(..., [])` that guards on `isStreaming === false` AND `loadingHistory === false` to survive React StrictMode double-renders.

### REQ-10 — Engram-down graceful degradation
When `ENGRAM_URL` is unreachable, `POST /api/chat` MUST still return 200, MUST still persist both `messages` rows in Postgres, MUST log WARNING for each dropped mirror, and MUST NOT surface the failure.

### REQ-11 — Postgres-down failure mode
When Postgres is unreachable, `POST /api/chat` MUST return 503 and `GET /api/chat/history` MUST return 200 with `{messages: []}`.

### REQ-12 — Test coverage
Pytest MUST cover REQ-1 through REQ-11. `tests/test_llm_validator.py` mocks MUST expose the four REQ-5 methods (existing references at lines 170, 178, 197, 223 today point to absent methods).

### REQ-13 — Frontend build regression
`npm run build` in `frontend/` MUST succeed with no new TypeScript errors introduced by F12.

## Scenarios

### SCN-1 — Happy path: POST persists both rows + mirrors
- GIVEN an authenticated user with `user_id=7, project_id=42, session_id="arch-agent-user-7-project-42-chat"`, healthy Postgres + Engram
- WHEN the user sends `"Hola"` and the assistant streams a response
- THEN `POST /api/chat` returns 200 SSE
- AND `messages` contains two rows (`role=user`/`role=assistant`) committed in one transaction
- AND `engram_client.save` is called twice with `topic_key` scoped to `(user_id=7, project_id=42)` after the Postgres commit
- AND SSE event order is `event: sources` → `(event: token)*` → `event: done`

### SCN-2 — Reload restores history
- GIVEN 3 prior user+assistant turn pairs persisted for `(user_id=7, project_id=42)`
- WHEN the user reloads the chat page
- THEN `ChatWindow.tsx` `useEffect` fires once (StrictMode-safe)
- AND `loadHistory(42)` calls `GET /api/chat/history?project_id=42&limit=5`
- AND the response is 200 with 6 messages newest-first
- AND `chatStore.messages.length === 6` after the action resolves

### SCN-3 — Default limit returns last 5 turns
- GIVEN 20 messages persisted for `(user_id=7, project_id=42)` spanning 2 hours
- WHEN the client calls `GET /api/chat/history?project_id=42` (no `limit`)
- THEN the response contains exactly the 5 most recent messages ordered newest-first

### SCN-4 — Engram down + Postgres up
- GIVEN `ENGRAM_URL` returns connection refused
- WHEN the user sends a message
- THEN `POST /api/chat` returns 200 SSE
- AND both `messages` rows are persisted
- AND WARNING logs are emitted for each `engram_client.save` failure
- AND no exception reaches the user

### SCN-5 — Postgres down
- GIVEN the Postgres container is stopped
- WHEN the user sends a message THEN `POST /api/chat` returns 503
- AND `GET /api/chat/history?project_id=42` returns 200 with `{messages: []}`

### SCN-6 — Defensive scoping on `engram_client.search` + cross-user isolation
- GIVEN `engram_client.search(scope='project', query='auth', project=None, user_id=7)`
- WHEN the method is called THEN it raises `ValueError("project is required")`
- AND a cross-user test asserts `list_recent(session_id="…user-7…")` returns zero rows when called with `user_id=8`

### SCN-7 — SSE ordering + commit-before-yield
- GIVEN an in-flight `POST /api/chat`
- WHEN the stream yields events THEN the order is strictly `event: sources` first, then `(event: token)*`, then `event: done` last
- AND the Postgres transaction for both message rows commits BEFORE the `event: done` yield

### SCN-8 — Migration idempotency
- GIVEN migration `0008_add_messages_table.sql` has been applied
- WHEN the migration runs a second time THEN `CREATE TABLE IF NOT EXISTS messages (...)` succeeds with no error

## Data Model

| Entity | Store | Key fields | Notes |
|--------|-------|-----------|-------|
| `messages` | Postgres | id, session_id, project_id, user_id, role, content, citations JSONB, engram_observation_id | New table · REQ-1 |
| `UserSession.engram_state` | Postgres (JSONB) | engram_state | Persists the resolved `session_id` mapping per `(user_id, project_id)` |
| Engram observations | Engram v2.0.0-rc.6 HTTP | id, session_id, project, title, content, type | Sibling mirror only — Postgres remains source of truth |

No schema changes on the Engram server side (Engram v2 HTTP is write-only for observations; retrieval goes via `/context`).

## Out of Scope

- MCP-stdio transport for the Engram client
- Cross-user memory sharing
- Auto-summarization of long histories beyond the last-N window
- F11 LangChain agent runtime integration (PRs #69-74 remain OPEN; F12 is independent)
- `app/core/session_store.py` (dead code) refactor — deferred per ADR-011
- `tests/test_llm_validator.py` mock updates beyond the 4 REQ-5 methods (covered in F12.2)
- Frontend virtualization or pagination of historical messages beyond the `?limit=` parameter

## Risks

1. Disconnect after Postgres commit but before SSE `done` yield leaves the assistant row orphaned — acceptable; the next history call surfaces it.
2. Engram v2.0.0-rc.6 HTTP has no list-by-session endpoint — mitigated by Postgres-as-truth (REQ-4).
3. Cross-user leakage via `engram_client.search` — mitigated by REQ-5 defensive `project` check + SCN-6 cross-user test.
4. Zustand hydration under React StrictMode — mitigated by REQ-9 `isStreaming` + `loadingHistory` guards.
5. Migration drift between `schema.sql` and `migrations/0008_*` — REQ-1 mirrors verbatim.
6. Token growth in LLM context — hard cap N=5 default; `?limit=` max 50; long-range recall via `engram_client.get_context()` only on explicit request.
7. TTFT regression from synchronous save before yield — benchmark in F12.2 PR; fall back to fire-and-forget if >100ms.
8. Forward-looking tests assume a richer Engram API — REQ-12 closes the gap with 4 new mocks.

## References

- explore.md @ 8ae860f · Engram #44
- proposal.md @ 1cfcbc1 · Engram #45
- ADR-011 — Engram as conversation-history mirror @ 1cfcbc1
- ADR-005 — Engram as MCP of memory @ d139c9e
- Issue #14 — [F12] Engram MCP integrado (memoria)
- migrations/0003_sync_sessions_table.sql — idempotent ALTER pattern REQ-1 mirrors