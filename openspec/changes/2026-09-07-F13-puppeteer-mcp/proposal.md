# Proposal: F13 — Puppeteer MCP (Render Mermaid / HTML to PNG)

| Field | Value |
|---|---|
| Change slug | `F13-puppeteer-mcp` |
| Branch | `feature/F13-puppeteer-mcp` |
| Base SHA | `4c5a9d3` (post-merge of F11 + F12 into the F11 branch tip; `origin/development` untouched) |
| GitHub issue | [#17 — [F13] Puppeteer MCP integrado](https://github.com/danielCH26/arch-agent/issues/17) |
| Relationship | Extends [explore.md](explore.md) (`4c5a9d3`); implements ADR-007 Puppeteer line (`docs/adr/007-six-mcps.md:78`); sits on the F12 persistence seam (`app/api/chat.py:232-267` `_persist_turn`). |
| Capabilities (NEW) | `puppeteer-mcp-integration` → `openspec/specs/puppeteer-mcp-integration/spec.md`; `chat-attachments` → `openspec/specs/chat-attachments/spec.md` |
| Modified capability | `engram-conversation-memory` (delta: `attachments JSONB` column on `messages` + REQ-4 expansion to persist attachments in the pre-`done` transaction) |
| ADR to add | ADR-013 (sidecar + `streamable_http` choice + security posture) |
| Engram topic_key | `sdd/F13-puppeteer-mcp/proposal` (this file) |
| Phase | `sdd-propose` |
| Artifact store | hybrid (OpenSpec + Engram) |

---

## 1. Why

GitHub issue #17 commits F13 to render Mermaid (and, in the future, HTML) diagrams as inline PNG images in the chat. Today, every `assistant` message that ends with a fenced ```` ```mermaid ```` block is shown as raw code — the user has to mentally render it, paste it into mermaid.live, or rely on a Chainlit preview that fails on complex graphs. With the renderer wired, **the moment the model writes a fenced Mermaid block, the chat shows the rendered PNG below the assistant text**, with the source preserved for copy-paste. This is the first "diagram-as-first-class-output" capability in arch-agent: product-proposal flows (where C4 / sequence diagrams are the answer), trade-off conversations (where component graphs make the argument legible), and architecture reviews (where the user wants the model to draw what it just argued) all become inline rather than afterthoughts.

Two concrete advances for arch-agent as a product. **First**, it turns the assistant from "explains architecture in prose" to "draws and explains architecture" — a meaningful capability gap from Cursor / ChatGPT for technical users who already think in diagrams. **Second**, it activates the rendering seam that future F-changes will need anyway (PDF export, user-uploaded image analysis, custom graph types) — F13 is the first mover on a `streamable_http` sidecar pattern that the Filesystem / Fetch / Web Search MCPs in ADR-007 will reuse when they ship. ADR-007 named the package; F13 ships the architecture.

## 2. What changes

**Backend** — new `app/core/puppeteer_mcp.py` (~200 LOC, mirrors `app/core/context7_mcp.py`); extend `app/core/agent.py` to fetch Puppeteer tools additively and emit a `DIAGRAM_HINT` in the system prompt; new helpers `save_attachment(...)` / `list_attachments(...)` in `app/core/message_store.py`; new `app/models/message.py` `Attachment` shape (JSONB); new `app/api/attachments.py` `GET /api/chat/attachments/{id}` endpoint; extend `app/api/chat.py` `_persist_turn` (lines 232-267) to persist attachments inside the same pre-`done` transaction; SSE emits `event: attachment`.
**Infrastructure** — new `puppeteer-mcp` compose service based on a custom `node:20-bookworm-slim` image that pre-bakes `@modelcontextprotocol/server-puppeteer` + Chromium + `streamable_http` transport on `:8931/mcp`; new `infrastructure/puppeteer-mcp/Dockerfile`; `docker-compose.yml` delta (one new service + `mem_limit: 512m`).
**Migrations** — `migrations/0009_add_message_attachments.sql` (additive `attachments JSONB DEFAULT '[]'` on `messages`) + `schema.sql` mirror.
**Configuration** — `.env.example` entries near line 98: `PUPPETEER_MCP_URL=http://puppeteer-mcp:8931/mcp`, `PUPPETEER_RENDER_TIMEOUT_SECONDS=15`, `PUPPETEER_MAX_RENDER_BYTES=2097152`, `PUPPETEER_RENDER_RATE_LIMIT_PER_MINUTE=5`.
**Frontend** — extend `frontend/src/api/chat.ts` `dispatchSSEEvent` for `event: attachment`; extend `Message.attachments?: Attachment[]` in `frontend/src/stores/chatStore.ts`; render `<img src={a.url}>` inline in `frontend/src/components/MessageBubble.tsx`.
**Tests** — `tests/core/test_puppeteer_mcp.py` (mirror `test_context7_mcp.py`); extend `tests/api/test_chat.py` with `event: attachment` assertions; new `tests/api/test_attachments.py` (401 / 404 / 200); Vitest for `chatStore.test.ts` (attachment append) and `MessageBubble.test.tsx` (image render).
**ADRs** — new `docs/adr/013-puppeteer-mcp.md` recording the sidecar + `streamable_http` choice and the security posture.
**No changes** — `requirements.txt` (no new pip dep; `langchain-mcp-adapters==0.3.2` already supports `streamable_http`), `backend/Dockerfile` (stays Python-only), `frontend/src/api/attachments.ts` (no client; the `<img>` tag loads directly from the signed URL).

## 3. Approach chosen — `streamable_http` sidecar on the F12 persistence seam

**Compose stack delta.** A new `puppeteer-mcp` service replaces the in-container stdio path ADR-007's literal reading would have forced. The service builds from `node:20-bookworm-slim`, installs `@modelcontextprotocol/server-puppeteer` once at image-build time (so the `npx -y` cold fetch never happens at request time), launches Chromium once on container start (warm browser), and exposes the MCP `streamable_http` transport on `:8931/mcp`. The backend container stays Python-only: `app/core/puppeteer_mcp.py` constructs a `MultiServerMCPClient({"puppeteer": {"transport": "streamable_http", "url": "${PUPPETEER_MCP_URL}", "timeout": 30}})` — verbatim the F11 `context7_mcp.py` shape. The browser-lifecycle choice is **persistent-per-container**: warm on start, one Chromium process per sidecar instance, ~100–300 ms per render (vs ~1–2 s with per-request spawn). `mem_limit: 512m` on the sidecar turns OOM into a clean restart instead of host swap.

**Request path.** `POST /api/chat` → `run_agent` (already in `app/core/agent.py` from F11) fetches `puppeteer_screenshot` additively → agent invokes the tool on any Mermaid block it emitted → returns base64 PNG bytes + path → `app/api/chat.py:_persist_turn` (the F12 seam at lines 232-267) saves the file under `/app/uploads/screenshots/<uuid>.png` and inserts an `attachments` JSONB entry inside the same pre-`done` transaction that already writes the `messages` row → SSE emits `event: attachment\ndata: {"kind":"screenshot","mime":"image/png","url":"/api/chat/attachments/<id>?token=…","filename":"diagram-<ts>.png"}\n\n` → browser renders `<img>` inline. Two seam choices matter and both are non-negotiable: **the pre-`done` transaction guarantees** that the screenshot row + message row land atomically (REQ-3, extends F12 REQ-4), and **the signed query-string token (TTL ≤ 5 min)** is the only auth path that works with `<img src>` because browsers cannot send custom `Authorization` headers on image loads. The frontend never stores the token; it expires within the page lifetime.

## 4. Out of scope (v1)

- Arbitrary HTML rendering (F13 ships **Mermaid-only** — see Resolved Ambiguity #2; the HTML sanitizer path is reserved for F14).
- Multi-turn agent memory that drives rendering decisions (F13 uses the deterministic "always render Mermaid blocks the model produced" path; multi-turn memory-driven rendering is F14 because `run_agent` does not yet read conversation history).
- Horizontal scaling of the sidecar (single replica + `mem_limit: 512m`; a render queue is future work).
- Filesystem / Web Search / Fetch MCPs (ADR-007 commits them but they ship as separate changes — F13 establishes the sidecar + `streamable_http` pattern they will reuse).
- PDF export of diagrams (the `puppeteer_pdf` tool in the community `merill-git/mcp-server-puppeteer` fork is not adopted).
- Disabling or removing Chainlit; the new SPA-side rendering slot is additive.
- Switching the storage shape from JSONB to a normalized `message_attachments` table (promote when retention / deletion policies arrive — Resolved Ambiguity #3).

## 5. Capabilities (contract for `sdd-spec`)

### New Capabilities

- **`puppeteer-mcp-integration`** — MCP client config (`streamable_http` → `${PUPPETEER_MCP_URL}`), `MultiServerMCPClient` singleton, `get_puppeteer_tools()` async fetcher (5 s timeout), `PuppeteerUnavailable(reason=...)` exception class, `reset_client_for_tests()` helper, agent integration (additive `tools = context7_tools + puppeteer_tools`), system-prompt `DIAGRAM_HINT`, tool-surface filter (`puppeteer_navigate` / `puppeteer_click` / `puppeteer_fill` / `puppeteer_select` / `puppeteer_hover` removed before exposing to the agent; only `puppeteer_screenshot` + a hardened `puppeteer_evaluate` (data:-URL only) reach the LLM), per-call 15 s timeout + 2 MB byte cap, per-user 5/min rate limit. Becomes `openspec/specs/puppeteer-mcp-integration/spec.md`.
- **`chat-attachments`** — Storage shape (JSONB column on `messages`, additive on F12's `citations` JSONB precedent), `save_attachment(...)` / `list_attachments(...)` helpers, SSE `event: attachment` payload contract (`{kind, mime, url, filename}`), `GET /api/chat/attachments/{id}` endpoint with signed query-string token (TTL ≤ 5 min), 404 on cross-user / unknown id, correct `Content-Type` from the storage row. Becomes `openspec/specs/chat-attachments/spec.md`.

### Modified Capabilities

- **`engram-conversation-memory`** — Delta: (a) `messages.attachments JSONB DEFAULT '[]'` column (mirrors `citations` JSONB); (b) REQ-4 ("Persist atomically before `done`") extended to include attachment rows in the same transaction; (c) `list_recent(user_id, project_id, limit)` extended to fold attachments into the replayed message shape. Lives as a delta spec at `openspec/changes/2026-09-07-F13-puppeteer-mcp/specs/engram-conversation-memory.delta.md`; merged into the canonical spec during `sdd-archive`.

## 6. Resolved ambiguities

| # | Question | Decision | Rationale (1 line) |
|---|----------|----------|--------------------|
| 1 | Cross-project attachment isolation | **Yes** — `attachments` scoped to `(user_id, project_id)` like `messages` | F12 already established this seam (REQ-2 of `engram-conversation-memory`); consistency |
| 2 | Mermaid-only or arbitrary HTML for F13? | **Mermaid-only** | Issue body says "HTML/Mermaid"; HTML path needs a sanitizer (1-week project) — defer to F14 |
| 3 | JSONB column vs `message_attachments` table | **JSONB column on `messages.attachments`** | MVP-correct, one migration; promote to table when retention / deletion policies land |
| 4 | Auth on `/api/chat/attachments/{id}` | **Signed query-string token** (TTL ≤ 5 min), 404 on cross-user / unknown id | `<img src>` cannot carry `Authorization` headers; cookie approach conflicts with the JWT-in-`Authorization` posture |
| 5 | Per-user render rate limit | **5/min**; `degraded` event with `reason=puppeteer_rate_limited`; agent falls back to text description | Mirrors F11 REQ-6 degraded-event discipline |
| 6 | Per-call byte cap | **2 MB** (PNG of a typical Mermaid diagram is 20–100 KB) | Generous default; protects `backend_uploads` from accidental abuse |
| 7 | Multi-turn vs deterministic rendering | **Deterministic for F13** — always render Mermaid blocks the model produced | Multi-turn memory-driven rendering requires `run_agent` to read conversation history (F14) |
| 8 | Sidecar image: own build vs public Playwright image | **Own Dockerfile** (Node 20-bookworm-slim + Chromium pre-baked, ~600 MB) | Public `mcr.microsoft.com/playwright` is ~1.2 GB and not pin-stable |
| 9 | Browser lifecycle | **Persistent browser per sidecar** (warm on container start) | P95 render latency drops from ~1–2 s to ~100–300 ms |
| 10 | Trace hygiene in Langfuse | **No code change** — `_truncate_tool_result` already caps at 4000 chars (F11 REQ-9); screenshot bytes never reach the trace because the tool result is the URL / path, not the image | Already satisfied by F11 |

## 7. Affected components (paths pinned to HEAD `4c5a9d3`)

| Path | Impact | Purpose |
|------|--------|---------|
| `app/core/puppeteer_mcp.py` | **NEW** | `MultiServerMCPClient` singleton (streamable_http), `build_puppeteer_client`, `get_puppeteer_tools` (5 s timeout + tool-surface filter), `PuppeteerUnavailable(reason=…)`, `reset_client_for_tests` (mirror of `context7_mcp.py`). |
| `app/core/agent.py` | **MODIFIED** | Extend `_try_get_context7_tools` → `_try_get_external_tools` (or sibling fetcher); compose `tools = context7_tools + puppeteer_tools`; system prompt gains `DIAGRAM_HINT`. |
| `app/core/message_store.py` | **MODIFIED** | Add `save_attachment(db, message_id, kind, mime, storage_path, source_url) -> Attachment` and `list_attachments(db, message_id) -> list[Attachment]`. |
| `app/models/message.py` | **MODIFIED** | New `attachments` JSONB column (mirrors `citations` JSONB precedent at line 58); new `Attachment` typed dict shape. |
| `app/models/__init__.py` | **UNCHANGED** | No new ORM class (attachments live as JSONB); column declared in the existing `Message` table. |
| `app/api/chat.py` | **MODIFIED** | `_persist_turn` (line 232) extended to insert attachments in the same transaction; SSE `event_generator` emits `event: attachment`. |
| `app/api/attachments.py` | **NEW** (~60 LOC) | `GET /api/chat/attachments/{id}` — signed-token verification, cross-user 404, `Content-Type` from the row, streams from `/app/uploads/screenshots/<id>.png`. |
| `app/api/dependencies.py` | **MODIFIED (if needed)** | Add `get_message_store` dependency or piggyback on the existing one. |
| `migrations/0009_add_message_attachments.sql` | **NEW** | Idempotent `ALTER TABLE messages ADD COLUMN IF NOT EXISTS attachments JSONB NOT NULL DEFAULT '[]'::jsonb`. Mirrors `0008_add_messages_table.sql` pattern. |
| `schema.sql` | **MODIFIED** | Mirror the `ALTER TABLE` block for greenfield DB parity. |
| `infrastructure/puppeteer-mcp/Dockerfile` | **NEW** (~40 LOC) | `node:20-bookworm-slim` + system libs (`libnss3`, `libatk1.0-0`, `libxss1`, `libasound2`, `libgbm1`, `libcups2`) + `npm i -g @modelcontextprotocol/server-puppeteer` + Chromium pre-bake + warm-up entrypoint. |
| `docker-compose.yml` | **MODIFIED** | Add `puppeteer-mcp` service (port 8931 internal, `mem_limit: 512m`, restart: on-failure); `backend` gets `PUPPETEER_MCP_URL=http://puppeteer-mcp:8931/mcp`. |
| `.env.example` | **MODIFIED** | `PUPPETEER_MCP_URL`, `PUPPETEER_RENDER_TIMEOUT_SECONDS`, `PUPPETEER_MAX_RENDER_BYTES`, `PUPPETEER_RENDER_RATE_LIMIT_PER_MINUTE` near line 98. |
| `backend/Dockerfile` | **UNCHANGED** | Stays Python-only — the sidecar carries the Node + Chromium weight. |
| `requirements.txt` | **UNCHANGED** | `langchain-mcp-adapters==0.3.2` already supports `streamable_http`. |
| `frontend/src/api/chat.ts` | **MODIFIED** | `dispatchSSEEvent` handles `event: attachment`; `createChatStream` callbacks gain `onAttachment`. |
| `frontend/src/stores/chatStore.ts` | **MODIFIED** | `Message.attachments?: Attachment[]`; `sendMessage` accepts `onAttachment` callback that appends to the in-flight assistant message. |
| `frontend/src/components/MessageBubble.tsx` | **MODIFIED** | Render `<img src={a.url} alt={a.filename} className="max-w-md rounded-lg my-2" />` for each attachment. |
| `tests/core/test_puppeteer_mcp.py` | **NEW** | Singleton, tool-surface filter, `PuppeteerUnavailable(reason=...)`, `reset_client_for_tests`, recorded fixture. |
| `tests/api/test_chat.py` | **MODIFIED** | New SCN: when `run_agent` yields an attachment event, `_persist_turn` persists + SSE emits `event: attachment` with the expected payload. |
| `tests/api/test_attachments.py` | **NEW** | 401 without JWT, 404 for cross-user / unknown id, 200 + correct `Content-Type` for owned attachment, 401 for expired token. |
| `frontend/src/stores/chatStore.test.ts` | **MODIFIED** | Vitest for attachment append. |
| `frontend/src/components/MessageBubble.test.tsx` | **NEW** | Vitest for inline `<img>` render. |
| `docs/adr/013-puppeteer-mcp.md` | **NEW** | Locks: (a) sidecar + `streamable_http` over in-container stdio; (b) tool-surface filter (only `puppeteer_screenshot` + hardened `evaluate`); (c) per-call 15 s timeout + 2 MB cap; (d) per-user 5/min rate limit; (e) signed query-string token (TTL 5 min). |

## 8. Stack dependency

- **F11 PRs — MERGED at `4c5a9d3`.** F13 builds on F11's `app/core/agent.py` + `create_agent` runtime + `MultiServerMCPClient` singleton pattern + `CallbackHandler` wiring (F11 REQ-3 → F13 REQ-7 is automatic).
- **F12 PR — MERGED at `4c5a9d3`.** F13 attaches to F12's `app/api/chat.py:232-267` `_persist_turn` transaction block; F12 REQ-4 ("Persist atomically before `done`") extends to include attachment rows (REQ-3 of F13).
- **No new pip dependency.** `langchain-mcp-adapters==0.3.2` (pinned at `requirements.txt:23`) already covers `streamable_http`; the F11 archive-report documents that the adapter's `transport="http"` literal was acknowledged as `streamable_http` — F13 uses the correct literal from day one.
- **Compose stack: 9 → 10 services.** New `puppeteer-mcp` joins `backend`, `spa`, `db`, `engram`, `engram-proxy`, `langfuse-web`, `langfuse-api`, `langfuse-db`, `redis`. `puppeteer-mcp-proxy` is **not** needed (the sidecar exposes `streamable_http` directly; no stdio bridge required).

## 9. Success criteria

Mapped to the issue #17 acceptance criteria:

1. **Renderiza diagramas Mermaid como imágenes** → Given the agent's response contains a fenced Mermaid code block, When the SSE stream completes, Then the assistant message carries one `attachment` (kind=`screenshot`, mime=`image/png`, url=`/api/chat/attachments/<id>?token=…`) and `MessageBubble` renders the `<img>` inline. (REQ-1, REQ-3)
2. **Tool surface restricted** → Given `get_puppeteer_tools()` is called, When the returned list is inspected, Then it contains exactly `puppeteer_screenshot` + the hardened `puppeteer_evaluate(data:-URL only)`, and `puppeteer_navigate` / `puppeteer_click` / `puppeteer_fill` / `puppeteer_select` / `puppeteer_hover` are NOT present. (REQ-2)
3. **Trazas registradas en Langfuse** → Given `LANGFUSE_PUBLIC_KEY` + `LANGFUSE_SECRET_KEY` are set, When `POST /api/chat` completes (success or render failure), Then a Langfuse trace exists with `user_id`, `project_id`, model name, tool call names (`puppeteer_screenshot`), token counts, and latency. **Satisfied automatically** by F11's `CallbackHandler` wiring — no new tracer code. (REQ-7)

Plus negative criteria:

- **Cross-user attachment** → Given user A owns attachment `<id>`, When user B requests `GET /api/chat/attachments/<id>?token=…`, Then the response is **404** (not 403, to avoid existence leak). (REQ-4)
- **Expired / forged token** → Given a token older than 5 min or signed with a different secret, When the request hits the endpoint, Then the response is **401**. (REQ-4)
- **Per-call budget** → Given a Mermaid block that hangs Chromium past 15 s, When the timeout fires, Then `event: error` is emitted with `messages store unavailable` semantics (mirrors F12 SCN-7), the response still lands, and the next turn can render normally. (REQ-5)
- **Rate limit** → Given user X exceeds 5 renders in 60 s, When the next render is requested, Then the agent emits `event: degraded\ndata: {"reason":"puppeteer_rate_limited"}\n\n` and falls back to a textual diagram description. (REQ-6)
- **Sidecar unavailable** → Given the `puppeteer-mcp` container is down, When `POST /api/chat` is called, Then the agent emits `event: degraded\ndata: {"reason":"puppeteer_unavailable"}\n\n` and the chat still completes via RAG-only. (REQ-2, REQ-5)
- **No regression on existing tests** → `tests/api/test_chat.py` keeps passing (extended with new SCNs); F11 + F12 REQs remain green.

## 10. Risks and mitigations

| # | Risk | Severity | Mitigation |
|---|------|----------|------------|
| 1 | **Tool surface leakage** — a future MCP version renames / adds a tool and the agent suddenly has `puppeteer_navigate` again. | **CRITICAL** | REQ-2 hard-filter in `app/core/puppeteer_mcp.py:get_puppeteer_tools()` (positive allow-list, not negative deny-list); recorded fixture asserts the exact tool surface; ADR-013 §Security documents the filter as a hard invariant. |
| 2 | **Cross-user attachment leak** — misconfigured endpoint returns the PNG to the wrong user. | **HIGH** | REQ-4: cross-user returns **404** (not 403, to avoid existence leak); signed-token TTL ≤ 5 min; `tests/api/test_attachments.py` cross-user negative case (mirrors F12 SCN-6). |
| 3 | **Per-call budget bypass** — hung Chromium leaks memory and stalls renders. | **HIGH** | REQ-5: `asyncio.wait_for(timeout=15)` at the call boundary; per-call byte cap (2 MB) at the response handler; `mem_limit: 512m` on the sidecar container. |
| 4 | **Signed-token TTL abuse** — a leaked token within the 5-min window grants access to the attachment. | **HIGH** | REQ-4: TTL ≤ 5 min, secret rotated per token issuance; `Content-Disposition: inline` (not `attachment`) to discourage Save-As workflows; `_persist_turn` writes the token alongside the attachment row so revocation is a column update. |
| 5 | **Chromium memory ceiling** — ~200 MB RSS × 1 replica on developer laptops pushes Docker Desktop over 4 GB. | **MEDIUM** | REQ-2: persistent browser (one Chromium per container, not per request); `mem_limit: 512m` on the sidecar; ADR-013 documents the dev-laptop impact; single replica pinned in compose. |
| 6 | **Cold-start render latency** — first render of the day pays Chromium startup (~1–2 s). | LOW | REQ-2: warm-up on container start (`puppeteer.launch()` + `browser.close()` in the sidecar entrypoint). |
| 7 | **Migration drift** — `migrations/0009` and `schema.sql` diverge. | LOW | Mirror the `ALTER TABLE` in both files; `run_migrations.py` and `init_db.py` already apply both. |
| 8 | **Review budget** — backend ~700 LoC + frontend ~150 LoC + sidecar Dockerfile + compose delta = ~1000–1100 LoC. | MEDIUM | `delivery_strategy: single-pr` + `review_budget_lines: 800` cached; forecast slicing at `sdd-tasks` if a slice crosses 400 LoC. |

## 11. Rollback plan

1. **Stop and remove the sidecar** — `docker compose down puppeteer-mcp`; revert the `docker-compose.yml` delta (one service).
2. **Drop the migration** — `migrations/0009_add_message_attachments.sql` is reversible (`ALTER TABLE messages DROP COLUMN IF EXISTS attachments`); `schema.sql` reverts on the same commit.
3. **Revert `app/api/chat.py:_persist_turn`** — remove the attachment-insert block; SSE stops emitting `event: attachment`; the agent falls back to F11 + F12 behaviour. `GET /api/chat/attachments/{id}` returns 404 (or 410 Gone if explicitly removed).
4. **Revert the frontend** — `chatStore.Message.attachments` and `MessageBubble.tsx` `<img>` slot revert to undefined / no render; the frontend continues to work without rendering attachments.
5. **Revert `app/core/puppeteer_mcp.py`** — remove the file; `app/core/agent.py` reverts to `_try_get_context7_tools` only. `requirements.txt` stays unchanged.
6. **No data loss** — rollback never deletes rows that already exist (`messages.attachments` JSONB can be kept for forensic value or dropped; either is non-destructive to other tables).
7. **ADR-013 stays** — it documents the architectural decision; a future change can re-implement it without re-justifying the package / transport choice.

## 12. Delivery plan (single-pr with chained-slice forecast)

Forecast ~1000–1100 LoC across backend (~700 LoC) + frontend (~150 LoC) + sidecar Dockerfile + compose delta + ADR + tests. `delivery_strategy: single-pr` is cached; `review_budget_lines: 800`. The backend slice alone (~700 LoC) is the boundary — `sdd-tasks` will decide whether to:

- **(A) Single PR, ~1100 LoC.** Acceptable if reviewer is comfortable with a multi-area change; risk = larger diff to review in one pass.
- **(B) Chained PRs.** `F13.1 — sidecar + compose + Dockerfile + ADR-013 (~300 LoC)`, `F13.2 — Python wrapper + agent integration + storage + chat.py (~500 LoC)`, `F13.3 — frontend + attachments endpoint (~300 LoC)`. Each PR carries its own tests + verification.

`chained-pr` skill trigger = "PRs over 400 lines, stacked PRs, review slices" — applies if `sdd-tasks` forecasts any single slice > 400 LoC. The orchestrator's `apply` phase owns the final slice decision.

## 13. ADRs to add

- **ADR-013 — Puppeteer MCP sidecar + security posture** (mandatory). Records: (a) sidecar + `streamable_http` over in-container stdio (image-bloat avoidance); (b) tool-surface filter as a hard invariant (only `puppeteer_screenshot` + hardened `evaluate`); (c) per-call 15 s timeout + 2 MB byte cap; (d) per-user 5/min rate limit; (e) signed query-string token (TTL ≤ 5 min) for the attachment endpoint; (f) persistent browser per container (warm on start); (g) `mem_limit: 512m` on the sidecar. Path: `docs/adr/013-puppeteer-mcp.md`.

No second ADR for storage shape (folded into ADR-013 §Storage); no second ADR for the rate limit (folded into ADR-013 §Security).

## 14. References

- [explore.md](explore.md) (`4c5a9d3`) — 10 risks, 3 alternatives, 10 open questions resolved in §6.
- [ADR-007](../docs/adr/007-six-mcps.md) — names the Puppeteer package (`@modelcontextprotocol/server-puppeteer`) + transport; F13 implements.
- [ADR-010](../docs/adr/010-context7-agent-runtime.md) — `MultiServerMCPClient` singleton pattern (F11); F13 mirrors verbatim.
- [ADR-011](../docs/adr/011-engram-conversation-mirror.md) — F12 persistence seam (`_persist_turn`); F13 sits on it.
- [openspec/specs/context7-mcp-integration/spec.md](../specs/context7-mcp-integration/spec.md) — F11 REQ-9 (`_truncate_tool_result` 4000-char cap) protects Langfuse from screenshot bytes.
- [openspec/specs/engram-conversation-memory/spec.md](../specs/engram-conversation-memory/spec.md) — F12 REQ-4 ("Persist atomically before `done`"); F13 REQ-3 extends it to attachments.
- [Issue #17](https://github.com/danielCH26/arch-agent/issues/17) — Original scope (Puppeteer MCP integrado) — issue body in English.
- [langchain-mcp-adapters 0.3.2](https://pypi.org/project/langchain-mcp-adapters/) — supports `streamable_http` (verified in F11 explore + archive).
- [@modelcontextprotocol/server-puppeteer](https://github.com/modelcontextprotocol/servers/src/puppeteer) — Anthropic's reference server; streamable_http via `--port` flag.
- [MCP streamable_http transport spec](https://modelcontextprotocol.io/specification/2025-03-26/basic/transports#streamable-http).