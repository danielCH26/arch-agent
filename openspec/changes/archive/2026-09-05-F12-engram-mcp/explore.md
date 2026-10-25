# Exploration: F12 — Engram MCP (Memoria + Historial de Chat)

**Change slug:** `F12-engram-mcp`
**Capability:** `engram-conversation-memory` (NEW — `openspec/specs/engram-conversation-memory/spec.md`)
**Branch:** `feature/F12-engram-mcp`
**Base SHA:** `d139c9e` (origin/development @ merge of PR #64; LANGCHAIN agent runtime STILL does NOT exist on this branch — F11 modules `app/core/context7_mcp.py`, `app/core/agent.py`, `app/core/langfuse_tracer.py` remain OPEN in PRs #69–74)
**Engram topic_key:** `sdd/F12-engram-mcp/explore`
**Issue:** [#14](https://github.com/danielCH26/arch-agent/issues/14) — extended by orchestrator to cover **chat history persistence** in addition to project-decision memory.

---

## 1. Current State — what the codebase already gives F12

### 1.1 Engram client (`app/core/engram_client.py` — 65 LOC, NOT 54)

Methods present at `d139c9e`:

| Method | HTTP | Purpose | Used in F12 for |
|--------|------|---------|-----------------|
| `create_session(session_id, project, directory)` | `POST /sessions` | Open an engram session | Create per-(user,project) session lazily |
| `end_session(session_id, summary)` | `POST /sessions/{id}/end` | Close session with summary | (Optional) periodic GC |
| `save_observation(session_id, project, title, content, observation_type='discovery')` | `POST /observations` | Persist an observation | Save each chat message + decision |
| `get_context(project)` | `GET /context?project=&scope=project` | Pull compacted project context string | Inject into LLM prompt as long-term memory |
| `_request(method, path, body)` | (private) | urllib.request driver | n/a |

**Methods MISSING** (tests already reference them but they don't exist — see §1.5):
- `search(query, limit)` — for list/browse observations
- `get_observation(id)` — for full content
- `save(topic_key, content, title, type=...)` — kwargs-style write
- `delete(topic_key)` — invalidation

> **Decision point for proposal**: extend `EngramClient` with the missing retrieval methods, OR rely solely on Postgres for retrieval (§3 Alternatives).

### 1.2 Chat endpoint (`app/api/chat.py` — 197 LOC)

- Single route: `POST /api/chat` → SSE stream.
- `event_generator()` does `model.astream(prompt)` directly. **No `save_observation()` call anywhere in the file.**
- Already constructs `handler = SSEStreamCallbackHandler()` (line 121) but **never feeds it to `model.astream`** — dead object. (`tests/api/test_chat.py:45-53` only verifies the handler's init, not its callback flow.) F12 can either ignore or fold this in.
- Insertion point for write: after `for event in model.astream(prompt)` finishes and the `done` event is yielded (line 186), gather the accumulated assistant content and `save_observation` in a `try/finally` so a stream crash doesn't lose the user-side save.
- Insertion point for the user message: at the start of `event_generator` (line 165), AFTER ownership check but BEFORE the SSE yield — fires before the model starts streaming. Per-message persistence is natural because each request is one user→assistant turn pair.

### 1.3 Session model (`app/models/session.py` — 14 LOC, no `Message` model)

```python
class UserSession(Base):
    __tablename__ = "sessions"
    id            = Column(Integer, primary_key=True)
    user_id       = Column(Integer, ForeignKey("users.id"), unique=True)
    project_id    = Column(Integer, ForeignKey("projects.id"))
    active_phase  = Column(String(50))
    engram_state  = Column(JSON)         # ← unused by chat flow today
    last_seen_at, created_at, updated_at
```

- `app/models/__init__.py` registers only `User`, `Project`, `UserSession`, `UploadedDocument`, `DocumentChunk`, `ArchitectPattern`. **No `Message` / `ChatMessage` ORM.**
- `schema.sql` + 7 migrations (`0001…0007`): ZERO `messages` table.
- `app/core/session_store.py` defines `save_session_state(user_id, …)` and `load_session_state(user_id)` but **has zero callers** in the codebase (`grep -r save_session_state` returns only its own definition). The `engram_state` JSON column is effectively write-once-by-seed-script only.

### 1.4 Frontend chat store (`frontend/src/stores/chatStore.ts` — 152 LOC)

```typescript
// initial state
messages: []            // EMPTY on every page reload
isStreaming: false
error: null

// actions
sendMessage, addUserMessage, addSystemMessage,
addAssistantMessage, appendToLastAssistantMessage,
clearMessages, setError
```

- **No `loadHistory(projectId)` action.** `ChatPage.tsx` and `ChatWindow.tsx` have NO `useEffect` that fetches prior messages.
- Verified: `grep "messages.*=.*\[\]" frontend/` → 7 hits, all confirming empty-init pattern. None are "fetched-from-server".
- Today: page reload → empty chat. Frontend fix is small: add `loadHistory` + invoke on mount.

### 1.5 Forward-looking tests (`tests/test_llm_validator.py`)

Lines 170, 178, 197, 223 call `engram_client.search`, `engram_client.get_observation`, `engram_client.save`, `engram_client.delete` — **none of these exist on the client at `d139c9e`**. Production passes `engram_client=None`, so the failing paths aren't hit live. **F12 will inherit a partially-failing test surface** that assumes a richer Engram API. Two ways forward:

- (a) Add the methods to `EngramClient` to satisfy these tests (§3.B Alternative).
- (b) Refactor the validator's tests to mock `EngramClient` (no client-side change).

### 1.6 Engram runtime (live at HEAD `d139c9e`)

- Container `engram` running `serve 7438`, proxied to host `:7439` and to peers via `engram-proxy` socat on `:7437`.
- Healthcheck: `GET /health` → `200 {"service":"engram","status":"ok","version":"2.0.0-rc.6"}` (verified via `curl http://localhost:7439/health`).
- `ENGRAM_PROJECT` env var is set; `app/__init__.py:33-36` already defines `get_engram_project_key(user_id) → f"{ENGRAM_PROJECT}-user-{user_id}"` — per-user scope convention is established.

---

## 2. Engram HTTP surface — what we have vs. what F12 needs

Verified via `Invoke-WebRequest` against `http://localhost:7439` (socat host mapping) on Sun Sep 06 2026, version `2.0.0-rc.6`:

### 2.1 Endpoints that work

| Method | Path | Verified | Notes |
|--------|------|----------|-------|
| `GET` | `/health` | 200 `{"service":"engram","status":"ok","version":"2.0.0-rc.6"}` | Liveness only |
| `POST` | `/sessions` | 201 `{"id":"…","status":"created"}` | Body `{id, project, directory}` |
| `POST` | `/sessions/{id}/end` | 200 `{"id":"…","status":"completed"}` | Body `{summary}` |
| `POST` | `/observations` | 201 `{"id":N,"status":"saved"}` | Body `{session_id, project, type, title, content, scope}` |
| `GET` | `/context?project=…&scope=project` | 200 `{"context":"…"}` | Compaction/recall (returns empty when project has none) |
| `DELETE` | `/sessions/{id}` | **409 Conflict** | Sessions cannot be deleted; only ended |

### 2.2 Endpoints that did NOT work (probed)

```
GET  /sessions                                    → 405 (POST only)
GET  /sessions/test                               → 404 (not implemented)
GET  /sessions/test/observations                  → 404
GET  /sessions/test/messages                      → 404
GET  /observations                                → 404 (POST only)
GET  /observations?project=…&limit=5              → 404
GET  /observations?session_id=…                   → 404
GET  /observations/list?session_id=…             → 400 (path exists, no schema match for live sessions)
GET  /observations/recent                         → 404
GET  /search?q=…                                  → 404 (this is MCP-only in v2)
GET  /v1/observations                             → 404
GET  /api/v1/observations                         → 404
GET  /projects                                    → 404
GET  /memories                                    → 404
GET  /history?project=…                           → 404
GET  /stats                                       → 404
GET  /openapi.json                                → 404 (no OpenAPI surface)
```

### 2.3 Gap analysis — F12 requirements vs. v2.0.0-rc.6 HTTP API

| F12 need | HTTP available? | Workaround |
|----------|-----------------|------------|
| **Persist** a chat message | ✅ `POST /observations` | None — covered by `save_observation()` |
| **Persist** a project decision | ✅ `POST /observations` | Same — covered |
| **List** last N chat messages for a (user, project) | ❌ HTTP list endpoint absent | Use Postgres `messages` table; or sqlite-direct; or MCP transport |
| **Search** semantically across decisions | ⚠️ Only via MCP tools (stdio), not HTTP | F12 can switch to MCP for reads if proposal goes MCP-first |
| **Reconstruct session_id** for retrieval | ⚠️ `get_engram_project_key(user_id)` exists, but engram has no list-by-session over HTTP | Persist `session_id` in `users`/`sessions` JSONB and reuse it |

> **Hard finding**: the Engram v2.0.0-rc.6 HTTP API is **write-only** for observations and **read-only via `/context`** (a pre-computed digest, not a per-observation browser). For chat history retrieval specifically, F12 **must** store messages somewhere Postgres-readable, OR switch the whole pipeline to MCP-stdio transport.

---

## 3. Open Questions for Proposal Phase

The proposal MUST resolve:

1. **Storage choice** — pure Postgres (`messages` table) vs pure-Engram observations (read via MCP) vs hybrid (Postgres = truth, Engram = sibling copy for semantic recall).
   - Hybrid is tempting because ADR-005 already commits us to Engram for project memory. But it doubles the write path and creates consistency concerns (what if Engram is down?).

2. **Persistence cadence** — synchronous before SSE stream (blocks TTFT by ~50-200ms), post-stream (cleaner but risks losing the user message on crash), or fire-and-forget background task.
   - Recommendation checkpoint: synchronous-per-turn with `try/finally` is the lowest-risk pattern; the engram round-trip is fast (local socket).

3. **Retrieval strategy on page load** — last N messages (configurable; e.g. 50), summary-of-the-past + recent tail (LLM-cost), or Engram semantic-search top-K (cheap to compute, but doesn't give chronological order).
   - N=20 by default with `?limit` override is a sane default for `ChatPage`.

4. **`session_id` scope** — per-user (one `arch-agent-user-{user_id}-chat` session, infinite lifetime, observations grow unbounded) vs per-project (one session per `(user, project)` pair, easier to scope/enumerate).
   - ADR-005 calls out per-user isolation. Per-project chat fits the existing data model (already scope chat by `project_id`) and lets `/observations/list?session_id=…` in the future return only that conversation.

5. **Frontend load pattern** — `useEffect` on mount (fresh-load reads history once) vs lazy (load-on-first-input) vs SWR-style with revalidation. Mount-once is simplest; needs a `loadingHistory` flag in the store.

6. **Schema migration** — `app/models/message.py` new file + new migration `0008_add_messages_table.sql`. Or skip the model and use raw SQL in the chat route.
   - Test the trade-off: SQLAlchemy ORM adds `Base.metadata` registration + autogenerate friction. Raw SQL keeps the change small but loses type safety and tests.

7. **What to pass to the LLM prompt** — when context grows, do we inject history verbatim (token cost) or summarise (latency cost) or skip history entirely and rely only on Engram `/context` digest?
   - F12 should at minimum inject last-5-turns for grounding, AND surface the rest through `get_context()` only when the user explicitly asks.

8. **Failure mode** — what happens when Engram is down (container restarts) on persist? Swallow + log? Bubble 503? The current `EngramClient._request` raises `EngramError` after `URLError`.
   - For chat history in particular, **silently degrade** is the right answer (the message still streams to the user; we just lose persistence). For decisions / context injection, fail loud.

---

## 4. Alternatives Considered

### A. **Postgres-only** (canonical messages table, no Engram for chat)

- Add `Message` model + migration `0008_add_messages_table.sql` (columns `id, user_id, project_id, role, content, sources_json, engram_observation_id NULL, created_at`).
- Insert both rows in a single Postgres transaction.
- Retrieval = `SELECT … ORDER BY created_at DESC LIMIT N`.
- **Pros**: simplest, ACID, queryable, no coupling to Engram availability, FTS-ready via `tsvector` later.
- **Cons**: violates ADR-005's spirit ("memory lives in Engram"). Need a separate replication path for semantic recall of past decisions across conversation boundaries. Loses the "zero-dependency on chat backend for memory" property.
- **Effort**: Low (≤150 LoC + 1 migration + tests).

### B. **Engram-only** (every message is an observation; read via MCP)

- Extend `EngramClient` with `search()`, `get_observation()`, `save(topic_key=…)`, `delete(topic_key=…)` (the methods tests already anticipate).
- Hook up a `mcp` python client (stdio subprocess) OR add a thin HTTP list endpoint to a forked engram (out of scope here).
- Persist via `save_observation(session_id="user-N-project-M-chat", title="msg-{ts}", content=msg_json, type="chat_message")`.
- Retrieval = `engram_client.search(query=user_id, limit=N)` filtered by topic prefix.
- **Pros**: uniform with project-decision memory; ADR-005 preserved; no new DB table.
- **Cons**: §2.2 confirms v2 HTTP API has no list-by-session; would require either the MCP transport (additional `mcp` dependency on the backend) or sqlite-direct coupling to `engram_data` volume.
- **Effort**: Medium-High (≥300 LoC + MCP transport integration + tests; the missing-method extensions touch `tests/test_llm_validator.py` too).

### C. **Hybrid (Postgres = truth, Engram = sibling for semantic recall)** *(recommended)*

- `Message` model holds canonical chat history (`messages` table).
- After commit, async fire-and-forget `engram_client.save_observation(...)` to mirror into Engram for long-term recall (semantic / FTS across decisions and chats).
- Retrieval = Postgres `SELECT … ORDER BY created_at DESC LIMIT N`.
- For long-term cross-session recall: `engram_client.get_context(project)` already aggregates what Engram knows.
- **Pros**: clean separation of hot/warm data; chat UI never blocks on Engram; Engram stays the semantic brain.
- **Cons**: dual-write (mitigated with `try/except` around the Engram call, fire-and-forget).
- **Effort**: Medium (≈200-250 LoC across model, route, store, frontend store + tests).

---

## 5. Risks (≥5, ranked)

1. **Engram write-after-stream race**. If we persist in `try/finally` AFTER `yield event: done`, a client disconnect mid-stream leaves the user-message saved but the assistant-response lost. Fix: persist both rows in the same transaction (Postgres) with a short timeout, before yielding `done`.
2. **Engram v2.0.0-rc.6 HTTP API has no chat-list endpoint** (verified §2.2). Pure-Engram retrieval requires either forking engram or adopting MCP-stdio transport in the backend, both substantial. Switching to "MCP inside FastAPI" introduces a separate runtime (`mcp` Python SDK + subprocess lifecycle).
3. **Cross-user memory leakage**. ADR-005 names per-user isolation via `get_engram_project_key(user_id)`. If F12 indexes by `(user, project)` into one Engram session, an `engram_client.search()` for context could leak across projects without explicit `project` filter. The pattern must stay strict.
4. **`session_store.py` is currently dead code** — `save_session_state`/`load_session_state` have no callers. If F12 picks Hybrid (C) and uses `engram_state` JSONB, it must OWN this module (delete, refactor, or document).
5. **SSE handler is half-wired**. `chat.py:121` constructs `SSEStreamCallbackHandler` but never threads it into `model.astream(prompt)`. Either F12 reuses it to collect tokens into a buffer for persistence, or it can remove the dead construct. Tests in `tests/api/test_chat.py:45-53` will keep passing either way.
6. **Frontend Zustand hydration**. The store is module-level (`create()`), so React StrictMode double-renders or fast-refresh can stomp `messages` mid-stream. Once F12 adds `loadHistory` on mount, it must guard against `isStreaming === true` and not clobber in-progress messages.
7. **Migrations hygiene**. Adding `messages` requires `migrations/0008_add_messages_table.sql` + reference in `schema.sql` for greenfield DBs (matching the pattern in `0003_sync_sessions_table.sql`). Forgetting `schema.sql` means new `init_db.py` runs produce an incomplete DB.
8. **Token growth in LLM context**. Last-N verbatim injection balloons the prompt. With `multilingual-e5-small` + whatever the provider's LLM is, budgets differ. F12 must leave a knob (`history_window`, default 5 turns) and NOT default to "all history".
9. **Forward-looking tests in `tests/test_llm_validator.py`**. They call `engram_client.search`, `engram_client.get_observation`, `engram_client.save`, `engram_client.delete` — none of which exist on the client at `d139c9e`. They pass only because production passes `engram_client=None`. When F12 adds those methods, the tests' mocks will need updating to match the new signatures.

---

## 6. References

- **Issue** — https://github.com/danielCH26/arch-agent/issues/14 (extended to include chat history persistence).
- **ADR-005** — `docs/adr/005-engram-mcp.md` (commit is upstream; rationale: zero-runtime-deps, SQLite+FTS5, 19 MCP tools, single Go binary).
- **Live Engram** — running container, port mapping `:7439` → `:7437`, version `2.0.0-rc.6`, healthcheck `GET /health` → 200.
- **Backend** — `app/api/chat.py` (197 LoC, no persistence today), `app/models/session.py` (14 LoC, has unused `engram_state JSONB`), `app/core/engram_client.py` (65 LoC, 4 public methods + 1 private), `app/core/session_store.py` (37 LoC, dead code today), `app/__init__.py:33-36` (`get_engram_project_key`), `app/api/sse.py` (47 LoC, half-wired handler).
- **DB** — `schema.sql` (no `messages` table), `migrations/0001…0007_*.sql`, no `0008` yet.
- **Frontend** — `frontend/src/stores/chatStore.ts` (152 LoC, no `loadHistory`), `frontend/src/components/ChatWindow.tsx` (63 LoC, no fetch on mount), `frontend/src/pages/ChatPage.tsx` (66 LoC, only loads project metadata).
- **Tests** — `tests/test_engram_client.py` (43 LoC, uses `unittest` + `mock.patch('app.core.engram_client.urlopen')`), `tests/api/test_chat.py` (109 LoC, does NOT cover persistence), `tests/test_llm_validator.py` (forward-looking assertions on methods that don't exist yet on the client).
- **Sessions & SDD** — `openspec/` does not yet exist on this branch (`Test-Path openspec → False`); the proposal phase must create it.
- **Base SHA** — `d139c9e` ("Merge pull request #64 from danielCH26/feature/Pipeline_RAG_PGVector"). F11 PRs #69-74 are OPEN, NOT merged. F12 plans against the d139c9e baseline.
