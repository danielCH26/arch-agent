# Design: F13 — Puppeteer MCP (Render Mermaid → PNG)

| Field | Value |
|---|---|
| Change slug | `F13-puppeteer-mcp` |
| Capabilities (NEW) | `puppeteer-mcp-integration`, `chat-attachments` |
| Capability (DELTA) | `engram-conversation-memory` (REQ-EM-DELTA-1 `attachments JSONB` column) |
| Branch | `feature/F13-puppeteer-mcp` @ `4c5a9d3` |
| Issue | [#17 — [F13] Puppeteer MCP integrado](https://github.com/danielCH26/arch-agent/issues/17) |
| Proposal | `proposal.md` (this folder) · Engram `sdd/F13-puppeteer-mcp/proposal` |
| Spec | `openspec/specs/puppeteer-mcp-integration/spec.md` + `chat-attachments/spec.md` + `engram-conversation-memory` DELTA |
| ADR to add | ADR-013 — Puppeteer MCP sidecar + security posture |
| Delivery | Forecast ~1,250 LoC; `delivery_strategy: single-pr` but **above the 400-line single-PR cap** → flagged for `sdd-tasks` slicing (§8 Q-NEW-LOC-CAP) |
| Engram topic_key | `sdd/F13-puppeteer-mcp/design` |

> **Scope lock (from `puppeteer-mcp-integration/spec.md` §Scope Confirmation and `chat-attachments/spec.md` §Scope Confirmation).** F13 is **Mermaid-only**: the agent invokes `puppeteer_screenshot` exclusively on a fenced `mermaid` block it just emitted. Arbitrary HTML rendering (sanitizer, `puppeteer_navigate` allow-list, `data:`-URL externalization) is **OUT of scope** and reserved for F14. This design honours that constraint: the hardened `puppeteer_evaluate` and the tool-surface allow-list (§4) exist only to support the Mermaid render path; no HTML payloads flow through them in F13.

---

## 1. Overview

F13 turns the assistant from "explains architecture in prose" into "draws and explains architecture". Today every fenced ```mermaid``` block lands in the chat as raw code; with F13 the moment the model emits the block, the chat shows the rendered image inline with the source preserved for copy-paste. This is the first **diagram-as-first-class-output** capability in arch-agent: product-proposal flows (C4 / sequence), trade-off conversations (component graphs), and architecture reviews all become inline rather than afterthoughts. (product-proposal §1, §2.)

F13 also activates the sidecar + `streamable_http` seam that ADR-007 commits and that future F-changes (Filesystem, Fetch, Web Search MCPs) will reuse without re-architecting — the `puppeteer-mcp` sidecar establishes a 10-service compose ceiling that the next MCPs fit. Concretely F13 ships: a Node 20 sidecar running `@modelcontextprotocol/server-puppeteer` over `streamable_http`, a Python wrapper mirroring `context7_mcp.py` (singleton, `build_*_client`, `get_*_tools`, typed `PuppeteerUnavailable`), a `messages.attachments JSONB` column with a pre-`done` transaction seam extending F12 REQ-4, a signed-token `GET /api/chat/attachments/{id}` endpoint, and an `event: attachment` SSE channel the frontend renders inline. (proposal §3, §4; spec `puppeteer-mcp-integration` REQ-PMCP-1..5, `chat-attachments` REQ-ATT-1..3.)

---

## 2. Architecture

```text
       SPA (React)                         FastAPI backend                Sidecar                Postgres
  ┌──────────────────┐    SSE         ┌───────────────────────┐   streamable_http   ┌─────────────────┐
  │ MessageBubble    │ ──────────────►│ app/api/chat.py       │ ──────────────────► │ puppeteer-mcp   │
  │  <img src=url?>  │  event:        │   event_generator     │   :8931/mcp         │  @modelcontext..│
  │                  │   sources      │     ─ retrieve ctx    │                     │  /server-puppet │
  │ chatStore        │   token*       │     ─ run_agent  ─────────────►  LangChain    │  Chromium warm  │
  │  onAttachment    │   attachment   │       ─ yields:       │                     │  ~200MB RSS     │
  │   → push to msg  │   done         │         token/tool_   │                     └─────────────────┘
  └──────────────────┘                │         start/end/    │                              │
                                      │         attachment/   │ ── 2-arg Mermaid HTML ──►   │
                                      │         done          │                              │
                                      │     ─ _persist_turn   │                              ▼
                                      │       ONE tx: msg row │                     ┌─────────────────┐
                                      │       + attachments   │ ──save PNG bytes──► │ /app/uploads/   │
                                      │         JSONB entries │                     │  screenshots/   │
                                      │     ─ yield done      │                     │  <uuid>.png     │
                                      └───────────────────────┘                     └─────────────────┘
                                                                       ▲
                                          GET /api/chat/attachments/{id}?token=<signed>
                                                                       │
                                                          ┌────────────┴────────────┐
                                                          │ app/api/attachments.py  │
                                                          │  verify token (TTL 5m)  │
                                                          │  scope by (user,id)     │
                                                          │  404 cross-user; 200 OK │
                                                          └─────────────────────────┘
```

### 2.1 Compose stack delta

| Service | Image | Mem | Purpose |
|---|---|---|---|
| `puppeteer-mcp` *(NEW)* | custom `node:20-bookworm-slim` (Dockerfile at `infrastructure/puppeteer-mcp/Dockerfile`) | `mem_limit: 512m` | `@modelcontextprotocol/server-puppeteer` + pre-baked Chromium; exposes `:8931/mcp` over `streamable_http`. Warm-on-start (`puppeteer.launch()` + `browser.close()` in `entrypoint.sh`) eliminates ~1–2s cold render. One Chromium per sidecar (persistent), single replica. |
| `backend` *(MOD)* | UNCHANGED Python-only image | UNCHANGED | Gains env: `PUPPETEER_MCP_URL=http://puppeteer-mcp:8931/mcp`, `PUPPETEER_RENDER_TIMEOUT_SECONDS=15`, `PUPPETEER_MAX_RENDER_BYTES=2097152`, `PUPPETEER_RENDER_RATE_LIMIT_PER_MINUTE=5`. `depends_on: puppeteer-mcp: condition: service_started`. |

Stack grows from **9 → 10 services**. No `puppeteer-mcp-proxy` (socat): `streamable_http` runs on the sidecar directly; no stdio bridge required.

### 2.2 Tool-surface allow-list — where the filter lives

Mirrors F11's `_try_get_context7_tools` at `app/core/agent.py:190-211`. `app/core/puppeteer_mcp.py:get_puppeteer_tools()` (analogous to `context7_mcp.py:172-215`) calls `client.get_tools(server_name="puppeteer")`, then **positive-filter** the result list before returning:

```python
_PUPPETEER_ALLOWED_TOOLS = frozenset({"puppeteer_screenshot"})

async def get_puppeteer_tools(client=None):
    raw = await asyncio.wait_for(client.get_tools(server_name="puppeteer"), timeout=15.0)
    return [t for t in raw if t.name in _PUPPETEER_ALLOWED_TOOLS]  # positive allow-list
```

The hardened `puppeteer_evaluate` from REQ-PMCP-2 is **not** a live tool — it is the *name* of a wrapper tool registered server-side (or, per the cleanest path, a sub-tool of `puppeteer_screenshot` invoked with a `mode="data_url"` argument). The agent only ever sees `puppeteer_screenshot`. `puppeteer_navigate` / `_click` / `_fill` / `_select` / `_hover` are filtered out **before** the list reaches the LLM (ADR-013 §Security; SCN-PMCP-3). A future MCP-server version adding `puppeteer_*` tools cannot leak through: the allow-list is the single source of truth, asserted by `tests/core/test_puppeteer_mcp.py::test_allow_list_filter`.

### 2.3 Rate limiter

In-memory `dict[user_id, list[float]]` sliding window keyed by `user_id`. **Single-replica only** — resets on backend restart; promote to Redis in F14 if horizontal scaling arrives. ADR-013 §Security documents this as the R-SPEC-4 mitigation. Window = 60s; limit = `PUPPETEER_RENDER_RATE_LIMIT_PER_MINUTE` (default 5). 6th call → `PuppeteerUnavailable(reason="puppeteer_rate_limited")` → SSE `event: degraded` with `reason="puppeteer_rate_limited"` (REQ-PMCP-4, SCN-PMCP-6).

---

## 3. Data model

### 3.1 Migration `0009_add_message_attachments.sql` (NEW, idempotent)

```sql
-- Migration 0009: messages.attachments JSONB (F13, issue #17)
-- Capability: chat-attachments (REQ-ATT-1) + engram-conversation-memory DELTA-1.
-- Additive, idempotent; re-runs are no-ops (ADD COLUMN IF NOT EXISTS).
ALTER TABLE messages
    ADD COLUMN IF NOT EXISTS attachments JSONB NOT NULL DEFAULT '[]'::jsonb;
```

Mirrored verbatim in `schema.sql` immediately after the `CREATE TABLE messages` block (line 131). SCN-EM-DELTA-1 / SCN-EM-DELTA-2 verified.

### 3.2 ORM change (`app/models/message.py`, +5 LOC)

Add one column mirroring the `citations` JSONB precedent at line 58–62:

```python
attachments = Column(
    JSON().with_variant(JSONB(), "postgresql"),
    nullable=False,
    server_default=text("'[]'"),
)
```

**Decision: JSONB column only — no new `Attachment` ORM class.** Mirrors the proposal §6 row 3 rationale (MVP simplicity; promote to a normalized `message_attachments` table when retention / deletion policies arrive). `app/models/__init__.py` UNCHANGED.

### 3.3 Attachment JSON shape (typed dict, not ORM)

```python
AttachmentType = {"screenshot"}  # only value in F13; PDF/SVG deferred
Attachment = TypedDict("Attachment", {
    "id": str,            # UUID v4 — used in /api/chat/attachments/{id}
    "kind": Literal["screenshot"],
    "mime": Literal["image/png"],
    "filename": str,      # "diagram-<unix_ts>.png"
    "storage_path": str,  # "/app/uploads/screenshots/<id>.png" — server-only
    "source_url": str | None,  # data:-URL the renderer was given (for audit)
    "bytes": int,         # size on disk; validated against PUPPETEER_MAX_RENDER_BYTES
})
```

`storage_path` is **server-only** — the SSE payload strips it and exposes only `{kind, mime, url, filename}` to the frontend. `url` is the public `/api/chat/attachments/<id>?token=<signed>` form.

### 3.4 On-disk layout

`/app/uploads/screenshots/<uuid>.png` (existing `backend_uploads` volume, subdir `screenshots/` created at backend boot via a 3-line `_ensure_uploads_dir()` helper in `app/core/attachment_tokens.py` startup, called from `app/main.py:on_startup`). Filename pattern `diagram-<unix_ts>.png` per SCN-ATT-6. UUID v4 generated with `uuid.uuid4()` (stdlib).

### 3.5 Signed-token scheme (`app/core/attachment_tokens.py`, NEW, ~40 LOC)

```python
# Wraps itsdangerous.URLSafeTimedSerializer.
# Key = SHA-256(JWT_SECRET_KEY); salt = "attachment-token"; max_age = 300s.
def sign_attachment_token(attachment_id: str, user_id: int, ttl: int = 300) -> str: ...
def verify_attachment_token(token: str, attachment_id: str, user_id: int) -> bool: ...
```

Why `itsdangerous` and not the existing `app/core/jwt`: `<img src>` cannot carry `Authorization`; signed URL = proven alternative; the JWT helper signs full JWTs, not query tokens. **Single new pip dep: `itsdangerous==2.1.2`** (already a transitive dep of FastAPI / Starlette — listed explicitly in `requirements.txt` for honesty).

---

## 4. API contracts

### 4.1 SSE event: `event: attachment`

| Field | Value |
|---|---|
| Name | `attachment` |
| Data shape | `{kind: "screenshot", mime: "image/png", url: "/api/chat/attachments/<id>?token=<signed>", filename: "diagram-<ts>.png"}` |
| Ordering | Emitted AFTER the last `event: token` and BEFORE `event: done`. Extends F12 SCN-7 ordering. |
| Frequency | **One per assistant turn** (concatenated PNG of all Mermaid blocks stacked vertically via the server-built HTML template). Zero if no Mermaid block (REQ-PMCP-1 SCN-PMCP-2). |

**Why one PNG per turn, not one per block**: a single stacked image is what the user wants ("here is the architecture" — one PNG, not a scrollable list), keeps the SSE channel quiet, and fits the pre-`done` transaction semantics (the agent produces one final render call). Concatenation is the server-side `puppeteer_evaluate` HTML template, not a frontend concern. The agent invokes `puppeteer_screenshot` at most once per turn; the render tool returns base64 + the multi-block HTML it was given.

### 4.2 `GET /api/chat/attachments/{id}?token=<signed>`

| Header / Status | Behaviour |
|---|---|
| `200 OK` | `Content-Type: image/png` (from stored row), `Content-Length: <bytes>`, `Content-Disposition: inline; filename="diagram-<ts>.png"`, `Cache-Control: private, max-age=300`. Body streamed via FastAPI `FileResponse` from `/app/uploads/screenshots/<id>.png`. |
| `401 Unauthorized` | Token missing, malformed, expired (>5 min), or signed with a different secret. **Do NOT log at WARNING** — same posture as `chat_history` (avoid info-leak via log fingerprints). |
| `404 Not Found` | Attachment id doesn't exist OR is not owned by the current `(user_id, project_id)`. Never 403 — to avoid existence leak (REQ-ATT-2, SCN-ATT-4). |

Auth posture: **query-string token only**. The endpoint does NOT call `get_current_user`; the signed token binds `(attachment_id, user_id)` so cross-user requests fail verification → 401 (covered path) or, if token-but-mismatch, the DB lookup returns zero rows → 404 (defense in depth). Both paths return indistinguishable 404s to a probing client.

---

## 5. File-by-file changes

### 5.1 Backend (Python)

| File | LOC | Change |
|---|---|---|
| `app/core/puppeteer_mcp.py` (NEW) | ~200 | Mirrors `context7_mcp.py:1-221`. Module-level `_CLIENT` singleton; `build_puppeteer_client()` (reads `PUPPETEER_MCP_URL` at call-time, builds `MultiServerMCPClient({"puppeteer": {"transport": "streamable_http", "url": ..., "timeout": 30.0}})`); `get_puppeteer_tools()` with `asyncio.wait_for(timeout=15.0)`; `_PUPPETEER_ALLOWED_TOOLS = frozenset({"puppeteer_screenshot"})` positive allow-list applied AFTER fetch; in-memory sliding-window rate-limiter `_check_rate_limit(user_id) -> bool` (5/60s); `PuppeteerUnavailable(reason=...)` with sub-reasons `puppeteer_timeout` / `puppeteer_unavailable` / `puppeteer_rate_limited` / `puppeteer_byte_cap`; `reset_client_for_tests()`. |
| `app/core/attachment_tokens.py` (NEW) | ~40 | `sign_attachment_token(attachment_id, user_id, ttl=300) -> str` + `verify_attachment_token(token, attachment_id, user_id) -> bool` via `itsdangerous.URLSafeTimedSerializer`; `_ensure_uploads_dir()` boot hook; key = `hashlib.sha256(JWT_SECRET_KEY.encode()).digest()`; salt = `b"attachment-token"`. |
| `app/core/agent.py` | +30 | New sibling `_try_get_puppeteer_tools()` (mirrors `_try_get_context7_tools()` at lines 190-211). Compose `tools = context7_tools + puppeteer_tools` at `_create_agent` (line 118-122). Yield exactly one `degraded` event with `source="puppeteer"` on any `PuppeteerUnavailable` reason. New `DIAGRAM_HINT` constant appended after `LIBRARY_HINT` in `_build_system_prompt` (line 113-115): instructs the model to invoke `puppeteer_screenshot` on each fenced ```mermaid``` block it emits, with a single merged HTML template. |
| `app/core/message_store.py` | +40 | `save_attachment(db, message_id, kind, mime, storage_path, source_url, bytes) -> dict` returns a typed `Attachment` dict (no ORM); mutates the parent `Message.attachments` JSONB list in-place via `Message.attachments = (Message.attachments or []) + [att]` and `db.flush()`. `list_attachments(db, message_id) -> list[dict]`. `save_message()` signature gains `attachments: list[dict] \| None = None` and merges them into the row's JSONB column inside the same flush. |
| `app/models/message.py` | +5 | New `attachments` JSONB column mirroring `citations` precedent (line 58-62). See §3.2. |
| `app/api/chat.py` | +60 | `_persist_turn` (lines 232-267) extended: accepts `attachments: list[dict] \| None`; `_persist_turn()` writes the assistant row with `attachments=` populated (the actual attachment-row inserts are inline inside `save_message` so they share the transaction). SSE `event_generator` (lines 280-313) gains one new `if event_name == "attachment":` branch that serialises `{kind, mime, url, filename}` (strips `storage_path`); `run_agent`'s yield contract is extended — agents yield `{"event": "attachment", "data": {...}}` between the last `token` and `done`. `_patch_chat_route` collaborators gain `save_attachment` mock. |
| `app/api/attachments.py` (NEW) | ~80 | `GET /api/chat/attachments/{id}` route. Steps: (1) read `?token=`, call `verify_attachment_token(token, id, user_id)` → 401 on miss; (2) look up `Message` by id with `attachments JSONB` containing the id → 404 (the lookup itself cross-checks `(user_id, project_id)` ownership so 404 is the only outcome for cross-user); (3) `FileResponse(path, media_type=att["mime"], headers={"Content-Disposition": f'inline; filename="{att["filename"]}"', "Cache-Control": "private, max-age=300"})`. Explicit `HTTPException(401)` and `HTTPException(404)` branches; no WARNING logs on these paths (avoid info-leak; mirrors `chat_history` posture). |
| `app/api/__init__.py` | +2 | Register `attachments` router alongside the existing chat router. |
| `app/main.py` | +5 | Startup hook `await attachment_tokens._ensure_uploads_dir()`. |
| `migrations/0009_add_message_attachments.sql` (NEW) | ~5 | Idempotent `ALTER TABLE messages ADD COLUMN IF NOT EXISTS attachments JSONB NOT NULL DEFAULT '[]'::jsonb;` (see §3.1). |
| `schema.sql` | +1 | Mirror the `ALTER TABLE` block after the `messages` table definition (line 131). |
| `infrastructure/puppeteer-mcp/Dockerfile` (NEW) | ~30 | `FROM node:20-bookworm-slim`; `RUN apt-get update && apt-get install -y --no-install-recommends libnss3 libatk1.0-0 libatk-bridge2.0-0 libxss1 libasound2 libgbm1 libcups2 fonts-liberation ca-certificates && rm -rf /var/lib/apt/lists/*`; `RUN npm i -g @modelcontextprotocol/server-puppeteer` (pre-bake); `RUN npx -y @modelcontextprotocol/server-puppeteer --version` (warm cache); `COPY entrypoint.sh /entrypoint.sh`; `ENTRYPOINT ["/entrypoint.sh"]`; `EXPOSE 8931`. |
| `infrastructure/puppeteer-mcp/entrypoint.sh` (NEW) | ~10 | `#!/bin/sh`; `set -e`; warm Chromium once (`npx -y @modelcontextprotocol/server-puppeteer --help >/dev/null 2>&1 || true`); exec `npx -y @modelcontextprotocol/server-puppeteer --port 8931 --executable-path /usr/bin/chromium` (the upstream server's `--port` flag activates `streamable_http` per the MCP transport spec). |
| `infrastructure/puppeteer-mcp/.dockerignore` (NEW) | ~5 | Standard Node ignores (`node_modules`, `npm-debug.log`, `.env*`, `.git`). |
| `docker-compose.yml` | +25 | New `puppeteer-mcp:` service block (build context `./infrastructure/puppeteer-mcp`, `mem_limit: 512m`, `restart: unless-stopped`, `healthcheck` via `wget --spider http://localhost:8931/health || exit 0`); `backend.depends_on` gains `puppeteer-mcp: condition: service_started`; `backend.environment` gains `PUPPETEER_MCP_URL: http://puppeteer-mcp:8931/mcp`. |
| `.env.example` | +4 | `PUPPETEER_MCP_URL=http://puppeteer-mcp:8931/mcp`, `PUPPETEER_RENDER_TIMEOUT_SECONDS=15`, `PUPPETEER_MAX_RENDER_BYTES=2097152`, `PUPPETEER_RENDER_RATE_LIMIT_PER_MINUTE=5` (defaults near line 98, mirroring the F11/F12 `.env.example` block). |
| `backend/Dockerfile` | 0 | **UNCHANGED** — stays Python-only; the sidecar carries the Node + Chromium weight. |
| `requirements.txt` | +1 | `itsdangerous==2.1.2` (only new pip dep). |
| `docs/adr/013-puppeteer-mcp.md` (NEW) | ~150 | Locks §2.2 allow-list, §2.3 rate limiter, §4.2 404 posture, §3 storage choice (JSONB → table migration path), browser lifecycle, `mem_limit`. |

**Backend total: ~640 LOC** (under 800-line budget; above 400-line single-PR cap — see §8 Q-NEW-LOC-CAP).

### 5.2 Frontend (TypeScript)

| File | LOC | Change |
|---|---|---|
| `frontend/src/api/chat.ts` | +20 | `StreamCallbacks` gains `onAttachment?: (att: {kind: 'screenshot'; mime: 'image/png'; url: string; filename: string}) => void`. `dispatchSSEEvent` (lines 38-87) handles `event: attachment` → calls `callbacks.onAttachment?.(JSON.parse(rawData))`. |
| `frontend/src/stores/chatStore.ts` | +30 | `Message` interface gains `attachments?: Attachment[]` where `Attachment = {kind: 'screenshot'; mime: 'image/png'; url: string; filename: string}`. `sendMessage` (lines 44-107) passes `onAttachment` callback that appends to the in-flight assistant message's `attachments` list via `state.messages.map(...)`. `loadHistory` (lines 166-187) propagates attachments if `ChatHistoryMessage` gains the field (see history endpoint below). |
| `frontend/src/components/MessageBubble.tsx` | +15 | Inside the assistant `<div>` (line 333-342), after `renderMarkdownBlocks(message.content)`, render `<img src={a.url} alt={a.filename} className="max-w-md rounded-lg my-2" loading="lazy" />` for each attachment with `kind === "screenshot"`. **No download button in v1** — see §8 Q-NEW-DOWNLOAD-PNG. |
| `frontend/src/api/chat.ts` (history extension) | +10 | `ChatHistoryMessage` interface gains `attachments?: Attachment[]`; `fetchChatHistory` parses it. |
| `frontend/src/components/__tests__/MessageBubble.test.tsx` (NEW) | ~60 | Renders with empty `attachments` (no `<img>`); with one attachment (one `<img>` with `src` matching the signed URL); with user message (no attachments slot). |
| `frontend/src/stores/__tests__/chatStore.test.ts` | +30 | Extends to assert `onAttachment` callback pushes into the in-flight assistant message's `attachments`. |

**Frontend total: ~165 LOC.**

### 5.3 Tests

| File | LOC | Target REQ |
|---|---|---|
| `tests/core/test_puppeteer_mcp.py` (NEW) | ~150 | REQ-PMCP-2 (allow-list filter, recorded fixture `["puppeteer_screenshot"]` exact), REQ-PMCP-3 (15s timeout + 2MB byte cap), REQ-PMCP-4 (5/min sliding window — `freezegun` or sleep), PuppeteerUnavailable sub-reasons. Mirrors `test_context7_mcp.py` (`tests/core/test_context7_mcp.py:1-315`). |
| `tests/core/test_attachment_tokens.py` (NEW) | ~50 | REQ-ATT-2: sign+verify happy path; expired token (>5 min, `freezegun`); tampered payload (`hmac` mismatch); cross-attachment-id reuse rejected. |
| `tests/api/test_attachments.py` (NEW) | ~120 | REQ-ATT-2 / REQ-ATT-3: 401 missing token, 401 expired, 404 cross-user, 404 unknown id, 200 happy path with `Content-Type` + `Content-Disposition` assertions. Mirrors `tests/api/test_chat_history.py`. |
| `tests/api/test_chat.py` | +30 | Extend `_patch_chat_route` (lines 198-262) to mock `save_attachment` + the new `event: attachment` SSE path. New SCN: when `run_agent` yields an `attachment` event, route persists row + emits `event: attachment` with `{kind, mime, url, filename}` and the URL contains a non-empty `token=`. |

**Test total: ~350 LOC. Full change total ≈ 1,155 LOC.**

---

## 6. Test plan (REQ → test file)

| Spec REQ | Test files |
|---|---|
| REQ-PMCP-1 (render + emit `event: attachment` before `done`) | `tests/api/test_chat.py` (new SCN) |
| REQ-PMCP-2 (positive allow-list; `puppeteer_navigate` absent) | `tests/core/test_puppeteer_mcp.py::test_allow_list_filter` (recorded full-tool-set fixture) |
| REQ-PMCP-3 (15s timeout + 2MB byte cap) | `tests/core/test_puppeteer_mcp.py` |
| REQ-PMCP-4 (5/min rate limit → `degraded`) | `tests/core/test_puppeteer_mcp.py` |
| REQ-PMCP-5 (Langfuse span automatic) | No new code — F11 CallbackHandler wiring covers it; assertion lives in `tests/api/test_chat.py` existing Langfuse mocks |
| REQ-ATT-1 (atomic persist; rollback on either-side fail) | `tests/api/test_chat.py` new SCN (simulated `SQLAlchemyError` on `save_message(assistant)` rolls back attachment rows) |
| REQ-ATT-2 (signed-token auth + 401/404 semantics) | `tests/api/test_attachments.py` + `tests/core/test_attachment_tokens.py` |
| REQ-ATT-3 (Content-Type + Content-Disposition from row) | `tests/api/test_attachments.py` |
| REQ-EM-DELTA-1 (`attachments JSONB` column) | `tests/test_schema_sync.py` extension (already on the F12 backlog) + manual migration re-run assertion in `tests/core/test_message_store.py` |

---

## 7. Migration plan (rollout)

1. **Phase 0 — no behaviour change.** Add `puppeteer-mcp` compose service + `infrastructure/puppeteer-mcp/*` (image builds but unused); ship migration `0009` (idempotent — re-running against F12 DB is a non-destructive additive ALTER). Backend image unchanged. Frontend unchanged. Verify `docker compose up -d puppeteer-mcp` succeeds and `wget --spider http://puppeteer-mcp:8931/health` returns 200. (proposal §11.)
2. **Phase 1 — backend off by default.** Merge F13 but set `PUPPETEER_RENDER_RATE_LIMIT_PER_MINUTE=0` in `.env` so `_check_rate_limit` rejects every render → agent emits exactly one `event: degraded` with `reason="puppeteer_rate_limited"` and falls back to text. SSE channel + attachment persistence compile and unit-test; no production user hits the sidecar. Verify smoke test on `/api/chat` (one render gets `degraded`, chat still streams).
3. **Phase 2 — enable.** Flip `PUPPETEER_RENDER_RATE_LIMIT_PER_MINUTE=5` in `.env` (and `.env.example`). Run a synthetic Mermaid prompt through `/api/chat`; confirm `<img>` renders in the SPA, file lands under `/app/uploads/screenshots/<uuid>.png`, `events: attachment` carries the signed URL. Roll back by re-setting the rate limit to `0` (no code revert needed).

---

## 8. Open questions (carry forward — DO NOT resolve in design)

| ID | Question | Status |
|---|---|---|
| **Q2 Mermaid-only** | Locked by the proposal + both new specs' §Scope Confirmation. Flagged for user review at design-checkpoint. | **LOCKED** |
| **Q-NEW-DOWNLOAD-PNG** | Spec deferred; design marks it as an OPTIONAL 5-LoC frontend add in `MessageBubble.tsx` (a "Save" icon next to the `<img>` that calls `fetch(url)` + saves via `URL.createObjectURL`). Out of scope for `sdd-tasks`. | DEFERRED |
| **Q-NEW-AUTOSCROLL** | Frontend-only decision (does new `<img>` trigger `ChatWindow` autoscroll?); out of OpenSpec scope. | DEFERRED |
| **Q-NEW-RATE-LIMIT-STORAGE** | Design picks **in-memory `dict[user_id, list[float]]`** for MVP — per-process, resets on restart, single replica only. Document as R-SPEC-4 mitigation in ADR-013 §Security. Promote to Redis in F14 if horizontal scaling arrives. | RESOLVED (design) |
| **Q-NEW-LOC-CAP** | **Total forecast ≈1,155 LoC** — **exceeds the 400-line single-PR cap** (§E Review Workload Guard). Three viable slices: `F13.1` sidecar infra (`infrastructure/puppeteer-mcp/*`, `docker-compose.yml`, `.env.example`, ADR-013 — ~280 LoC); `F13.2` Python wrapper + agent integration + persistence (`puppeteer_mcp.py`, `attachment_tokens.py`, `agent.py`, `message_store.py`, `models/message.py`, `chat.py`, `attachments.py`, `main.py`, migration, `requirements.txt` — ~570 LoC); `F13.3` frontend + attachments endpoint tests (~305 LoC). `sdd-tasks` MUST slice OR record `size:exception` for a single PR. The orchestrator owns the call. | **FLAGGED — orchestrator decides** |