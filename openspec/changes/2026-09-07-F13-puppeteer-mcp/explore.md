# F13 — Puppeteer MCP (Render Mermaid / HTML to PNG) · Exploration

| Field | Value |
|---|---|
| Change slug | `F13-puppeteer-mcp` |
| Branch | `feature/F13-puppeteer-mcp` (NOT YET CREATED on `4c5a9d3` of `feature/F11-context7-mcp`) |
| Base SHA | `4c5a9d3` (`feature/F11-context7-mcp` @ merge of F11+F12; `git branch -a` shows zero `F13*` branches) |
| GitHub issue | [#17 — [F13] Puppeteer MCP integrado](https://github.com/danielCH26/arch-agent/issues/17) |
| Engram topic_key | `sdd/F13-puppeteer-mcp/explore` |
| Phase | `sdd-explore` |
| Artifact store | hybrid (OpenSpec + Engram) |

---

## 1. Current state — what the codebase already gives F13

### 1.1 ADR-007 already chose the package and the transport

`docs/adr/007-six-mcps.md` line 78 commits us to:

```yaml
"puppeteer": {
  "transport": "stdio",
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-puppeteer"]
}
```

That is **Anthropic's official reference server** (`@modelcontextprotocol/server-puppeteer`), invoked through `npx` over **stdio transport**. F13 is the implementation of an already-decided ADR; the proposal phase does NOT need to revisit the package choice unless §5 alternatives argue otherwise.

The ADR also commits the broader `mcp_config` shape (Context7 `http`, Engram `stdio`, Filesystem `stdio`, Web Search `http`, Fetch `stdio`) — F13 is the first non-Context7 MCP to land in code, so it establishes the stdio pattern for Engram / Filesystem / Fetch when those land.

### 1.2 F11 left a working streamable_http-MCP scaffold (`app/core/context7_mcp.py`)

`app/core/context7_mcp.py` (221 LOC) is the canonical pattern to mirror for F13:

- Module-level singleton (`_CLIENT`) + `build_*_client()` lazy initializer + `reset_*_client_for_tests()` for pytest.
- `get_*_tools(client=None)` async fetch with `asyncio.wait_for(timeout=5.0)`.
- Typed `Context7Unavailable(reason=...)` exception with sub-reasons (`context7_timeout`, `context7_unavailable`, `context7_rate_limited`).
- `langchain-mcp-adapters==0.3.2` is **already pinned** at `requirements.txt:23` and supports `stdio` / `streamable_http` / `sse` / `websocket` transports via the same `MultiServerMCPClient({...})` constructor. Verified via the F11 explore (`openspec/changes/archive/2026-09-05-F11-context7-mcp/explore.md:130-152`).
- `app/core/agent.py:118-122` (`_create_agent`) and `:125-144` (`build_agent`) already pass `tools=` to `langchain.agents.create_agent`. Adding a second `MultiServerMCPClient` for Puppeteer is additive; no agent-runtime change needed.

The stdio option for `MultiServerMCPClient` (verified per `langchain-mcp-adapters` 0.3.2 docs):

```python
from langchain_mcp_adapters.client import MultiServerMCPClient
client = MultiServerMCPClient({
    "puppeteer": {
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-puppeteer"],
        "timeout": 30.0,
    }
})
```

### 1.3 Backend image is Python-only — no Node.js, no `npx`, no Chrome

`backend/Dockerfile` is a multi-stage build with `FROM python:3.11-slim`. Runtime stage installs only `libpq5` + `curl` (lines 70-74). Final image is ~500MB. **There is no Node.js runtime, no Chromium, no Puppeteer, no `npx` on disk.** `requirements.txt` has zero Node-related deps.

This is the central constraint of F13. ADR-007's prescribed pattern (`npx -y @modelcontextprotocol/server-puppeteer`) **cannot run in-process** from the `backend` container — at least one of the three things must be added:

1. Node.js runtime inside the `backend` container (image bloat, package-manager conflicts with `pip`).
2. A new sidecar container running the Puppeteer MCP stdio server (the `engram-proxy` pattern at `docker-compose.yml:103-111`, but with Node).
3. Replace stdio with a custom streamable_http server (option C in §5).

The `engram-proxy` precedent (`alpine/socat:1.8.1.3` at `docker-compose.yml:104-106`) shows the project is comfortable with tiny sidecars; a Node-based sidecar is the natural extension.

### 1.4 F11/F12 already wired the SSE event surface — frontend silently drops tool events today

- `app/api/chat.py:321-327` already forwards `tool_start` and `tool_end` SSE events with `{tool, result_length, status}` payload (F11 REQ-7).
- `frontend/src/api/chat.ts:38-87` (`dispatchSSEEvent`) handles only `sources`, `token`, `done`, `error`. `tool_start` / `tool_end` / `degraded` are emitted by the backend but **silently dropped on the frontend**. The user-facing "diagram attached" experience does not exist today — F13 must add it.
- `frontend/src/stores/chatStore.ts` (188 LOC) only knows `Message { id, role, content, sources? }`. The `Message` interface needs an `attachments?: Attachment[]` field (new shape) and a corresponding `onAttachment` SSE callback in `createChatStream`.
- `frontend/src/components/MessageBubble.tsx` renders text + RAG sources. It needs a slot for inline image attachments (PNG / JPEG / SVG). Confirm exact file when design runs.

### 1.5 Storage for screenshot bytes

`backend_uploads` volume is already mounted at `/app/uploads` (`docker-compose.yml:56` and `backend/Dockerfile:90`); it persists user uploads today. Reusing it for chat-rendered screenshots is the cheapest path, but there is **no static mount** today — the SPA fetches everything through `/api/*`. Two options:

- Add a new endpoint `GET /api/chat/attachments/{id}` that streams from `/app/uploads/screenshots/{id}.png` (auth-gated by `get_current_user`).
- Serve via nginx in the `spa` container (cross-container volume: needs docker-compose change).

The DB has a `messages` table (F12, `app/models/message.py`, `migrations/0008_add_messages_table.sql`) with a `citations JSONB` column. Screenshots are NOT citations (citations are RAG sources), so we need either:

- A new `messages.attachments JSONB` column (migration `0009_add_message_attachments.sql` + schema.sql mirror).
- A new `message_attachments` table (id, message_id, type, mime, storage_path, source_url, created_at).

The JSONB column is simpler (no extra JOIN, no schema drift), but a normalized table scales better for retention policies and clean deletion when a `message` is purged. **Recommendation lives in the proposal**, but the explore establishes both options.

### 1.6 Langfuse is wired (F11 REQ-5) — third acceptance criterion is free

`app/core/langfuse_tracer.py` and `app/api/chat.py:167-172` already thread `CallbackHandler` into the agent's callback list when `LANGFUSE_PUBLIC_KEY` + `LANGFUSE_SECRET_KEY` are set. The "Trazas registradas" acceptance criterion from issue #17 is satisfied automatically the moment the tool is invoked through the same `create_agent(...)` runtime — no extra work needed in F13.

### 1.7 Multi-turn agent conversation context

`app/core/agent.py:286-358` (`run_agent`) already takes the user's `message` and `rag_documents`, builds a system prompt, and yields tool events. **It does NOT carry conversation history.** Today the agent is single-turn — every `POST /api/chat` is one isolated turn. F13 must decide: does the agent decide *when* to render a Mermaid diagram (needs conversation memory, which F12 wired the storage for but `run_agent` does not yet read) or does the route inject a deterministic "render this Mermaid" tool call after the agent finishes (single-turn path)?

---

## 2. Puppeteer MCP server options — comparison

### 2.1 Anthropic's reference server (`@modelcontextprotocol/server-puppeteer`)

- **Source**: `github.com/modelcontextprotocol/servers/src/puppeteer` (auto-published to npm as `@modelcontextprotocol/server-puppeteer`).
- **Transport**: stdio (default) AND streamable_http (per the server's `--port` flag in recent versions).
- **Tools exposed** (verified via the server's README, late 2025): `puppeteer_navigate`, `puppeteer_screenshot`, `puppeteer_click`, `puppeteer_fill`, `puppeteer_select`, `puppeteer_hover`, `puppeteer_evaluate`, `puppeteer_close`. **Screenshot returns base64 of the PNG bytes plus a file path** when `--executable-path` is set.
- **Browser**: launches Chromium via `puppeteer` (the npm package). Default mode is `headless: "new"` (a.k.a. "new headless mode" on Chrome ≥109). ~200MB download on first install.
- **Pros**: official, maintained, well-known tool names, streamable_http mode keeps the backend image Python-only (browser lives in the sidecar).
- **Cons**: launches a full Chromium per request unless told otherwise (~250-400MB RSS per process); `puppeteer_navigate` accepts arbitrary URLs (security §4).

### 2.2 Community `merill-git/mcp-server-puppeteer`

- Adds a `puppeteer_pdf` tool and a configurable `--executable-path` + `--browser` flag (chrome vs chromium).
- Same transport surface (stdio or streamable_http depending on version).
- **Pros**: PDF export is occasionally requested by reviewers who want to attach architecture diagrams to PRs.
- **Cons**: smaller community; the PDF tool was the primary differentiator; for an MVP focused on rendering Mermaid in chat, the official server already returns the PNG the user wants to "see in the chat".

### 2.3 Self-hosted custom stdio Python server (e.g., Playwright-based)

- `pip install playwright` + `playwright install chromium --with-deps` (~150-200MB Chromium binary + system libs into `~/.cache/ms-playwright`).
- Write a thin `mcp` Python server that wraps Playwright APIs as MCP tools.
- **Pros**: pure-Python stack (consistent with the rest of `backend/`); no Node.js dep; Playwright's `headless=True` is the production-grade option; can run inside the `backend` container.
- **Cons**: significant custom code to maintain (the server's tool surface, the MCP protocol handshake, the JSON-RPC framing); drift risk when MCP spec evolves; "not the prescribed MCP".

### 2.4 Recommendation for §5

Stick with the official **`@modelcontextprotocol/server-puppeteer`** as ADR-007 prescribes. The only real choice is **transport** (stdio in-container via `npx` vs stdio in sidecar vs streamable_http in sidecar) — covered in §5.

---

## 3. Dependency impact

### 3.1 Image & disk

- `@modelcontextprotocol/server-puppeteer` pulls `puppeteer` which pulls `chrome-launcher` + `chromium`. **Chromium binary alone is ~150-180MB compressed, ~280-350MB on disk after extraction.** Plus system shared libs (libnss3, libatk1.0, libxss1, libasound2, libgbm1, libcups2, etc.) on Debian slim — ~+80MB of apt packages.
- **Total image delta**: +400-500MB for a sidecar that bundles Chromium + the MCP server. **For the `backend` container** (image bloat if stdio-in-process via `npx`): same +400-500MB plus Node.js (~+200MB) → ~+700MB.
- **Cold start**: `npx -y @modelcontextprotocol/server-puppeteer` triggers an npm registry fetch + tarball extraction on the **first call only** if not pre-baked. Subsequent calls reuse the cached `~/.npm/_npx`. If the MCP server is in a sidecar image, pre-bake in the Dockerfile (`RUN npx -y @modelcontextprotocol/server-puppeteer --version`).

### 3.2 Runtime & memory

- Chromium RSS in headless mode: **~120-200MB per process** (varies by page complexity). Multiplied by concurrent renders → memory ceiling.
- Two browser lifecycle choices:
  - **Per-request browser** (launch on every MCP call, kill on `puppeteer_close`): clean, but each Mermaid render costs ~1-2s of Chromium startup. Bad UX for "render N diagrams" turns.
  - **Persistent browser per container**: one Chromium process per sidecar instance, reuse across MCP sessions via a singleton `Browser` object held by the server. ~+200MB per replica; render latency drops to ~100-300ms per call.
- **For docker-compose with a single replica** (current state): persistent-per-container is the right default. For future horizontal scaling: a render-queue or a session-pinned Chromium is needed; out of scope for F13.

### 3.3 Headless mode

- Chromium ≥109 supports `headless: "new"` (the so-called "new headless mode"), which is faster and the default in modern Puppeteer (≥19). The Anthropic server uses it by default.
- `headless: "old"` is being deprecated; plan for `headless: "new"` only.

### 3.4 Network egress

- The browser process inside the MCP server makes outbound HTTPS/HTTP for any `puppeteer_navigate` call. **In F13 we do not want this** — we render local HTML, not arbitrary URLs. The tool surface must be restricted or the HTML must be served from `data:` URLs or a localhost server spawned by the MCP server. ADR-007's "Filesystem" line "Filesystem expone datos sensibles | Solo accede a `/app/uploads`" is the right discipline; F13 should similarly restrict `puppeteer_navigate` to `about:blank` + `data:text/html,...` only.

### 3.5 Docker-base image

- Debian-slim is the current base (`FROM python:3.11-slim` in `backend/Dockerfile:29`). A dedicated Node + Chromium sidecar could use `node:20-bookworm-slim` (already has the shared libs) or `mcr.microsoft.com/playwright:v1.45.0-jammy` (purpose-built, ~1.2GB but pre-baked with all browser deps).

### 3.6 Build time

- Sidecar image (Node + npm cache + Chromium pre-bake) ≈ +3-5min on first cold build, ≈ +30s on incremental builds where only `app/` changed.
- In-container `npx` adds ~+30s to `backend` cold build for the npm fetch; subsequent rebuilds with cached `_npx` are sub-second.

---

## 4. Codebase mapping — what F13 will touch

### 4.1 Backend (Python)

| File | Change |
|---|---|
| `app/core/puppeteer_mcp.py` (NEW, ~150-220 LOC, mirrors `context7_mcp.py`) | `build_puppeteer_client()` (stdio or streamable_http config), `get_puppeteer_tools()` (5s timeout), `PuppeteerUnavailable(reason=...)`, `reset_client_for_tests()`. |
| `app/core/agent.py` | Extend `_try_get_context7_tools()` → `_try_get_external_tools()` (or add a sibling fetcher). Compose `tools = context7_tools + puppeteer_tools`. Update the system prompt with a second `DIAGRAM_HINT` so the agent knows when to invoke the diagram tool. **NO** structural rewrite — additive only. |
| `app/core/message_store.py` (F12) | Add `save_attachment(db, message_id, type, mime, storage_path, source_url) -> Attachment` and `list_attachments(db, message_id) -> list[Attachment]`. New `attachments` column on `messages` OR new `message_attachments` table — proposal decides. |
| `app/models/message.py` | New `Attachment` ORM + migration (or JSONB column). |
| `app/models/__init__.py` | Register `Attachment` if a new ORM class. |
| `migrations/0009_add_message_attachments.sql` (NEW) | Idempotent (`CREATE TABLE IF NOT EXISTS`) matching the F12 migration pattern. Mirror in `schema.sql`. |
| `app/api/chat.py` | Extend the SSE `event_generator` to emit a new event type when an assistant tool returns a render result: `event: attachment\ndata: {kind:"screenshot", mime:"image/png", url:"/api/chat/attachments/<id>", filename:"diagram-<ts>.png"}\n\n`. The route persists both `messages` rows + an `attachments` row inside the same pre-`done` transaction (extends F12 REQ-4). |
| `app/api/attachments.py` (NEW, ~50 LOC) | `GET /api/chat/attachments/{id}` — auth-gated (`get_current_user`), streams the file from `/app/uploads/screenshots/{id}.png` with correct `Content-Type`. 404 if attachment not found OR not owned by the current user. |
| `backend/Dockerfile` | If stdio-in-container path is chosen (§5.A): add `nodejs` + `npm` to runtime stage, add `PUPPETEER_SKIP_DOWNLOAD=true` (download on demand) or pre-bake. **Add system libs** (`libnss3`, `libatk1.0-0`, `libxss1`, `libasound2`, `libgbm1`, `libcups2`) if the MCP server launches Chromium in this container. |
| `docker-compose.yml` | If sidecar path is chosen (§5.B/§5.C): add `puppeteer-mcp` service + `puppeteer-mcp-proxy` (alpine/socat if stdio is unavoidable). |
| `.env.example` | Add `PUPPETEER_MCP_URL=` (for streamable_http mode), `PUPPETEER_RENDER_TIMEOUT_SECONDS=15` (per-call budget), `PUPPETEER_MAX_RENDER_BYTES=2097152` (2MB cap). |
| `requirements.txt` | No new dep needed — `langchain-mcp-adapters==0.3.2` already covers stdio. |
| `tests/core/test_puppeteer_mcp.py` (NEW) | Mirror `test_context7_mcp.py` (verified by `tests/api/test_chat.py:198-262` `_patch_chat_route` convention): `reset_client_for_tests`, tool-name fixture (recorded list: `puppeteer_navigate`, `puppeteer_screenshot`, …), timeout test, transport-error test. |
| `tests/api/test_chat.py` | Add SCN: when `run_agent` yields an `attachment` event, the route persists a row + emits `event: attachment` + the SSE bytes include `/api/chat/attachments/<id>`. Extend `_patch_chat_route` to patch `save_attachment`. |
| `tests/api/test_attachments.py` (NEW) | 401 without JWT, 404 for cross-user attachment, 200 + correct mime for owned attachment. |

### 4.2 Frontend (TypeScript)

| File | Change |
|---|---|
| `frontend/src/api/chat.ts` | Extend `dispatchSSEEvent` to handle `event: attachment` → `callbacks.onAttachment?.({kind, mime, url, filename})`. Extend `createChatStream` callbacks interface. |
| `frontend/src/stores/chatStore.ts` | Extend `Message` interface with `attachments?: Attachment[]`. Extend `sendMessage` to accept `onAttachment` callback that appends to the in-flight assistant message's `attachments` list. |
| `frontend/src/components/MessageBubble.tsx` | Render `<img src={a.url} alt={a.filename} className="max-w-md rounded-lg my-2" />` for each `attachment` with `kind === "screenshot"`. |
| `frontend/src/components/ChatInput.tsx` | No change (input is text-only). |
| `frontend/src/components/ChatWindow.tsx` | No change. |
| `frontend/src/api/attachments.ts` (NEW, ~20 LOC) | Reuse the existing `authStore.token` for the auth header on `/api/chat/attachments/{id}` (served as `<img src>` so headers are set by `fetch`, not the `<img>` element itself; the simplest path is a **signed URL** approach where the GET is a regular `<img src>` to a token-bearing query string — see Open Question §6.4). |

### 4.3 Ops / docs

| File | Change |
|---|---|
| `docs/adr/013-puppeteer-mcp.md` (NEW) | Records the §5 choice, the security posture, the per-call budget. |
| `scripts/setup-local.sh` (if it exists; verify) | Add `curl http://puppeteer-mcp:8931/health` health probe. |

---

## 5. Security & ops risks

1. **Arbitrary URL navigation** — `puppeteer_navigate` accepts any URL. A user-crafted prompt that asks "go check https://internal.corp/admin and screenshot it" instructs the agent to navigate to an intranet host and screenshot it. **Mitigation**: hard-restrict the tool surface to `puppeteer_screenshot` + `puppeteer_evaluate` ONLY (drop `navigate`, `click`, `fill`, `select`, `hover` from the agent's view by filtering `get_puppeteer_tools()` result). Even then, `evaluate` runs JS — see (2).
2. **JavaScript execution via `puppeteer_evaluate`** — full DOM + network access. A malicious user message that injects `<script>` tags into a "rendered" HTML template can exfiltrate via `fetch` to an external host. **Mitigation**: the Chromium process runs inside the docker network; default egress is blocked at the orchestrator level (compose networks don't allow outbound by default). For belt-and-braces: a per-render iframe sandbox (`sandbox="allow-scripts"`) without `allow-same-origin` and a CSP that disallows external network.
3. **`file://` access** — `puppeteer_navigate` with `file:///etc/passwd` reads the container's filesystem. **Mitigation**: explicit allow-list or restriction to `about:blank` + `data:` URLs.
4. **Arbitrary HTML / XSS surface** — the agent's "render" tool will receive Mermaid sources it wrote. If we ever extend it to arbitrary HTML, every user-supplied string passed to `puppeteer_evaluate("document.body.innerHTML = " + html)` is a script-injection vector. **Mitigation**: HTML is built server-side from Mermaid-only input in F13; reject `script` and event handlers in a sanitizer before piping to Puppeteer (DOMPurify in JS, or `bleach` in Python if we pre-process).
5. **Outbound network from the browser** — once `puppeteer_navigate` is called, the browser will load any external resource the page references (CDNs, Google Fonts, tracking pixels). **Mitigation**: render with `--disable-features=NetworkService` for non-network calls, OR serve a self-contained HTML payload via `data:` URLs and forbid the agent from emitting `<script src=…>` / `<img src=…>` (CSP `default-src 'self' 'unsafe-inline'` won't help because we control the input). Simplest: Chromium `--no-sandbox` is **unsafe** but required for rootless Docker; the right answer is to run Chromium as the unprivileged `appuser` (already exists in `backend/Dockerfile:89`).
6. **Render budget / DoS** — every Puppeteer call is a real browser navigation. A user that asks "render 50 diagrams" can starve the sidecar. **Mitigation**: per-call timeout (default 15s), per-call byte cap on the screenshot (e.g., 2MB), per-user rate limit (e.g., 5 renders / minute, returned as `degraded` with `reason=puppeteer_rate_limited`).
7. **Cold-start latency** — first render of the day pays Chromium startup (~1-2s) + npm fetch on cache miss. **Mitigation**: warm-up on container boot (`puppeteer.launch()` + `browser.close()` in the sidecar's entrypoint) + persistent browser-per-container.
8. **Memory ceiling** — Chromium RSS ~200MB × 1 sidecar replica = +200MB baseline on top of the current ~500MB `backend` image. **Mitigation**: pin a single replica in compose; add a memory limit (`mem_limit: 512m`) on the sidecar so OOM produces a restart instead of swapping the host.
9. **Frontend auth on `<img src>`** — `GET /api/chat/attachments/{id}` needs to be reachable by the `<img>` tag without an `Authorization` header (browsers don't send custom headers on `<img src>`). Two paths: (a) signed query-string token with a short TTL (recommended), (b) same-origin cookie. F13 should pick (a) and document the token-rotation policy in the ADR.
10. **Trace noise in Langfuse** — screenshot bytes are large; logging the full tool output in Langfuse would balloon storage. **Mitigation**: truncate the tool result in `app/core/agent.py:_truncate_tool_result` (already caps at 4000 chars per F11 REQ-9) and store the binary in `backend_uploads`, not in the trace metadata.

---

## 6. Alternatives considered

### A. **stdio in-container via `npx`** (ADR-007 literal reading)

Add Node.js + Chromium system libs + npm to `backend/Dockerfile`. Run `npx -y @modelcontextprotocol/server-puppeteer` as a subprocess spawned by `MultiServerMCPClient` per `app/core/puppeteer_mcp.py`.

| Aspect | Detail |
|---|---|
| **Pros** | Zero new docker-compose services. Matches ADR-007 verbatim. No network hop. |
| **Cons** | `backend` image grows by ~700MB (Node + Chromium + system libs); cold rebuilds get longer; the `MultiServerMCPClient` subprocess model makes per-process browser lifecycle awkward (each Python request spawns a fresh `npx` + Chromium unless we cache); if `appuser` is the runtime user, Chromium needs `--no-sandbox` (unsafe) or `--user-data-dir` under `/tmp`; Dockerfile complexity rises. |
| **Effort** | Medium (~250 LOC Python + 30-line Dockerfile delta). |
| **Risk** | Per-request Chromium startup kills P95 latency (~1-2s per render); image bloat for a single MCP. |

### B. **stdio sidecar container (`puppeteer-mcp` service)** *(recommended)*

New `puppeteer-mcp` service in `docker-compose.yml` based on a custom image that pre-bakes Node 20-bookworm-slim + `@modelcontextprotocol/server-puppeteer` + Chromium. The MCP server exposes stdio, but **also** exposes streamable_http on `:8931/mcp` for Python to reach over the docker network. `MultiServerMCPClient` config:

```python
{"puppeteer": {"transport": "streamable_http", "url": "http://puppeteer-mcp:8931/mcp", "timeout": 30}}
```

`backend/Dockerfile` stays Python-only. Persistent browser lives in the sidecar (one Chromium process per container; warm-up on start).

| Aspect | Detail |
|---|---|
| **Pros** | Backend image unchanged (~500MB stays). Puppeteer can stay running with persistent browser → low per-call latency (~100-300ms). The streamable_http transport uses `langchain-mcp-adapters` exactly like F11's Context7 pattern (`app/core/context7_mcp.py:82-89`). Independent resource limits (`mem_limit: 512m` on the sidecar). Security posture matches ADR-007's "isolated subprocess" spirit. |
| **Cons** | One new compose service (stack ceiling: 9 → 10, still under the 11-service precedent in F11 explore §1.4). Slight first-build penalty (~3-5min cold image build). |
| **Effort** | Medium (~250 LOC Python + 50-line Dockerfile for the sidecar + ~10-line compose delta). |
| **Risk** | Network hop is sub-ms on the docker network; not a real concern. |

### C. **Custom in-process Playwright server** (skip MCP entirely)

`pip install playwright` + `playwright install chromium --with-deps` in `backend/Dockerfile`. Add `app/core/diagram_renderer.py` that exposes three Python functions: `render_mermaid(code: str) -> bytes`, `screenshot_url(url: str) -> bytes`, `screenshot_html(html: str) -> bytes`. The agent uses these via LangChain's `@tool` decorator (`langchain.tools.tool`), bypassing MCP entirely.

| Aspect | Detail |
|---|---|
| **Pros** | No new compose service. No MCP protocol framing (one less moving part). Same Python wheel as the rest of the backend. Playwright's headless API is more battle-tested than Puppeteer for edge cases (iframes, downloads). |
| **Cons** | **Diverges from ADR-007** which commits to MCP. Future `get_engram_project_key`-style "memory tools" and the Filesystem / Web Search / Fetch MCPs would all be inconsistent. The agent runtime is now coupled to the renderer — a single tool implementation, not a protocol. |
| **Effort** | Lowest for F13 alone (~100 LOC + Dockerfile delta). Higher for F14+ because we lose the MCP scaffolding pattern. |
| **Risk** | ADR-007 reversal would have to be re-justified; this explore flags it as the **wrong long-term call** even if the shortest path. |

### Recommendation

**Alternative B (streamable_http sidecar)**. Rationale:

1. Preserves ADR-007's package choice (`@modelcontextprotocol/server-puppeteer`) — the ADR only names the package, not the transport.
2. Reuses the F11 `app/core/context7_mcp.py` pattern verbatim — the codebase already proves the `MultiServerMCPClient({"puppeteer": {"transport": "streamable_http", "url": ..., "timeout": ...}})` shape works.
3. Keeps `backend/Dockerfile` Python-only. Image delta lives in a separate sidecar with independent memory limits.
4. Persistent browser in the sidecar gives ~100-300ms render latency (vs ~1-2s with per-request spawn).
5. The 6-MCP roadmap (ADR-007) expects Context7 (HTTP), Engram (stdio), Puppeteer (stdio→streamable_http), Filesystem (stdio→streamable_http), Web Search (HTTP), Fetch (stdio→streamable_http). Establishing the **sidecar + streamable_http** pattern with F13 unblocks the Filesystem / Fetch MCPs without re-architecting.

C is the shortest path but breaks the architecture. A is the literal ADR reading but bloats the backend image and degrades latency. B wins on all five.

---

## 7. Open Questions for Proposal Phase

The proposal MUST resolve (some need user input before design):

1. **Who can see the rendered diagram?** The `messages` table is per-`(user, project)` (F12). The attachments column/table follows the same scope. Confirm cross-project isolation is acceptable (no shared "library of diagrams"). *(Likely yes, but worth stating.)*
2. **Mermaid-only or arbitrary HTML?** The issue body says "Herramienta para renderizar HTML/Mermaid". Decision: F13 ships Mermaid-only (the actual use case from ADR-007); the HTML path is reserved for a future F14. *Risk: scope creep into a HTML sanitizer is a 1-week project.*
3. **Storage shape**: new `messages.attachments` JSONB column vs new `message_attachments` table. JSONB is one migration + one column; the table is normalized. *Recommend JSONB for F13 (less code, same correctness for MVP); promote to a table if/when retention/deletion policies arrive.*
4. **Auth on `/api/chat/attachments/{id}`**: signed query-string token (TTL ≤ 5 min) vs cookie-based session. *Recommend signed token — the SPA already uses JWT in `Authorization`, the natural extension is a short-lived `attachment_token` query param.* Confirm token-rotation policy.
5. **Per-user rate limit**: how many renders per minute before the agent falls back to "describe the diagram in text" (analogous to F11 REQ-6 degraded event)? *Recommend 5/min, returning `degraded` with `reason=puppeteer_rate_limited`.*
6. **Per-call byte cap on the screenshot**: 2MB feels right; confirm. PNG of a typical Mermaid diagram is 20-100KB so 2MB is generous.
7. **Multi-turn vs single-shot rendering**: does the agent need conversation memory to decide *when* a diagram should be rendered (F12 wired the storage but `run_agent` doesn't read it), or is the deterministic "always render Mermaid blocks the model produced" path acceptable for F13? *Recommend deterministic for F13; multi-turn memory-driven rendering is F14.*
8. **Sidecar image: own build or public `mcr.microsoft.com/playwright`?** Public image is ~1.2GB; own Dockerfile is ~600MB. *Recommend own Dockerfile (slimmer, opinionated, easier to pin).*
9. **Browser lifecycle**: persistent (one Chromium per sidecar container, warm on start) vs per-request. *Recommend persistent for MVP; revisit if horizontal scaling is ever needed.*
10. **Trace hygiene in Langfuse**: confirm F11's `_truncate_tool_result` cap (4000 chars) is enough — screenshot bytes never reach the trace because the tool result is the URL/path, not the image. *Confirm; no change to `agent.py` likely needed.*

---

## 8. Stack constraints — verified

- `langchain-mcp-adapters==0.3.2` (pinned at `requirements.txt:23`) **supports stdio AND streamable_http** on the `MultiServerMCPClient` constructor. Verified via the F11 explore (`openspec/changes/archive/2026-09-05-F11-context7-mcp/explore.md:130-152`). F13 needs **no new dependency**.
- `langchain>=1.0,<2.0` (REQ-1 of the F11 spec) — the agent runtime already exists; F13 is purely additive on the `tools=` argument.
- `langfuse>=2.0.0` — third acceptance criterion (`Trazas registradas`) is satisfied automatically when the tool runs through `create_agent(...)`.
- `python:3.11-slim` (backend image) — Node.js is NOT installed; **adding a Node-based sidecar is the only viable stdio path** without bloating the backend image.
- F12 `messages` table (migration `0008_add_messages_table.sql`) and `messages.citations JSONB` — the storage seam for F13 lives next to it; same migration-numbering convention (`0009_…`).

---

## 9. Risks (ranked)

| # | Risk | Severity |
|---|---|---|
| 1 | **Sidecar service grows the compose stack by one** (10 services vs the current 9). Mitigation: bounded memory limits + documented in ADR-013. | LOW |
| 2 | **Chromium RSS ~200MB per sidecar replica** pushes Docker Desktop memory usage over 4GB on dev laptops. Mitigation: pin one replica + `mem_limit`; document in ADR. | MEDIUM |
| 3 | **Tool surface includes `puppeteer_navigate` and `puppeteer_evaluate`** which can leak data / hit external hosts if the agent is tricked. Mitigation: filter the tool list returned to the agent down to `puppeteer_screenshot` + a hardened `puppeteer_evaluate` (data:-URL only). | CRITICAL |
| 4 | **HTML injection / XSS** if the renderer ever accepts user-supplied HTML. Mitigation: F13 ships Mermaid-only input from the model; add an HTML sanitizer if/when HTML support lands. | MEDIUM |
| 5 | **Cold-start render latency ~1-2s** for the first call after a sidecar restart. Mitigation: warm Chromium on sidecar start; persistent browser. | LOW |
| 6 | **Per-call budget enforcement is missing** — without a timeout, a hung Chromium page leaks. Mitigation: `asyncio.wait_for(timeout=15)` in `get_puppeteer_tools()` (mirrors F11 REQ-6); per-call `puppeteer_screenshot({timeout: 10})` argument. | HIGH |
| 7 | **Frontend `<img>` auth** — current JWT-in-Authorization-header pattern doesn't work for `<img src>`. Mitigation: signed query-string token. | HIGH |
| 8 | **Cross-user attachment leak** if the attachments endpoint is auth-misconfigured. Mitigation: test_attachments.py cross-user negative case (mirrors F12 SCN-6). | HIGH |
| 9 | **Migration drift** — adding a new column or table without mirroring `schema.sql`. Mitigation: follow the F12 `0008_add_messages_table.sql` pattern; `run_migrations.py` and `init_db.py` must stay aligned. | LOW |
| 10 | **Review budget** — §4.1 + §4.2 totals ~600-700 changed lines; under the 400-line single-PR cap when the sidecar Dockerfile and `compose.yml` delta are counted separately. Mitigation: split into `F13.1` (sidecar infra + compose) + `F13.2` (Python wrapper + agent integration) + `F13.3` (frontend + attachments endpoint), or use the `single-pr` strategy and let the orchestrator slice if the apply phase reports `400-line budget risk: High`. | MEDIUM |

---

## 10. References

### Code paths verified at HEAD `4c5a9d3`

- `app/core/context7_mcp.py` (221 LOC) — canonical MCP wrapper pattern, `_CLIENT` singleton, `build_context7_client` / `get_context7_tools` / `Context7Unavailable(reason=…)` / `reset_client_for_tests`.
- `app/core/agent.py` (373 LOC) — `_try_get_context7_tools()` at line 190-211 is the seam to extend for Puppeteer.
- `app/core/langfuse_tracer.py` (78 LOC) — wires `CallbackHandler` when env vars are present.
- `app/api/chat.py` (426 LOC) — pre-`done` persistence block (F12 REQ-4) at line 232-267 is the seam for attachment persistence.
- `app/models/message.py` (81 LOC) — the storage shape; `messages.citations` JSONB precedent for an additive JSONB column.
- `app/core/message_store.py` (verified by `tests/core/test_message_store.py:74-133`) — `save_message`/`list_recent`/`ensure_user_session` helpers.
- `app/core/engram_client.py` (142 LOC) — F12-extended with `search`/`get_observation`/`save(topic_key=…)`/`delete`; precedent for the small, typed HTTP client wrapper.
- `migrations/0008_add_messages_table.sql` — the migration pattern F13 should mirror (`CREATE TABLE IF NOT EXISTS` + idempotent).
- `backend/Dockerfile` (103 LOC) — Python 3.11-slim only; runtime stage lines 70-74.
- `docker-compose.yml` (289 LOC) — `engram-proxy` pattern at lines 103-111 is the precedent for any new sidecar.
- `requirements.txt` (27 LOC) — `langchain-mcp-adapters==0.3.2` already covers stdio + streamable_http.
- `frontend/src/api/chat.ts` (206 LOC) — `dispatchSSEEvent` only handles `sources`/`token`/`done`/`error`; `tool_start`/`tool_end` are emitted but dropped today.
- `frontend/src/stores/chatStore.ts` (188 LOC) — `Message` interface needs an `attachments?: Attachment[]` field.
- `frontend/src/components/MessageBubble.tsx` — render slot for inline images (verify in design phase).
- `tests/api/test_chat.py` (894 LOC) — `_patch_chat_route` (lines 198-262) is the established patch-all-collaborators convention F13 must extend.
- `tests/core/test_message_store.py` (241 LOC) — SQLite-in-memory + subset-table fixture pattern.
- `.env.example` (99 LOC) — slot for `PUPPETEER_MCP_URL=` / `PUPPETEER_RENDER_TIMEOUT_SECONDS=` near line 98.

### ADRs

- `docs/adr/007-six-mcps.md` — names the Puppeteer package + stdio transport (line 78); F13 implements it.
- `docs/adr/001-langchain-framework.md` — names `MultiServerMCPClient` as the bridge.
- `docs/adr/010-context7-agent-runtime.md` — F11's runtime precedent; F13 follows.
- `docs/adr/011-engram-conversation-mirror.md` — F12's persistence seam; F13 sits next to it.

### External (authoritative)

- `@modelcontextprotocol/server-puppeteer` — Anthropic's reference server. Source: https://github.com/modelcontextprotocol/servers/src/puppeteer.
- `langchain-mcp-adapters==0.3.2` on PyPI — `MultiServerMCPClient` transports `stdio` / `streamable_http` / `sse` / `websocket`, runtime `headers=`, `handle_tool_errors` default.
- MCP transports spec: https://modelcontextprotocol.io/specification/2025-03-26/basic/transports#streamable-http.
- Chromium "new headless mode" — Chrome ≥109 default; Puppeteer ≥19.

### Issue

- #17 — [F13] Puppeteer MCP integrado — https://github.com/danielCH26/arch-agent/issues/17.

### Related changes (this branch / archived)

- `feature/F11-context7-mcp` @ `4c5a9d3` (current branch, MERGED with F12).
- `openspec/changes/archive/2026-09-05-F11-context7-mcp/{explore,proposal,design,spec,verify}.md` — F11's full deliverable trail.
- `openspec/changes/archive/2026-09-05-F12-engram-mcp/{explore,proposal,design,spec,verify}.md` — F12's full deliverable trail (storage + persistence seam; F13 sits on top).
- `openspec/specs/context7-mcp-integration/spec.md` — F11 spec (REQ-7 SSE tool events the frontend ignores today).
- `openspec/specs/engram-conversation-memory/spec.md` — F12 spec (REQ-4 commit-before-yield is the seam F13 attaches to).