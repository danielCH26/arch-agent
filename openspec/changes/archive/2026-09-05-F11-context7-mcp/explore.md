# F11 — Context7 MCP Integration · Exploration

| Field | Value |
|---|---|
| Change slug | `F11-context7-mcp` |
| Branch | `feature/F11-context7-mcp` |
| Base SHA | `d139c9e` (`origin/development`, post-merge of PR #64) |
| GitHub issue | [#13 — [F11] Context7 MCP integrado](https://github.com/danielCH26/arch-agent/issues/13) |
| Engram topic_key | `sdd/F11-context7-mcp/explore` |
| Phase | `sdd-explore` |
| Artifact store | hybrid (OpenSpec + Engram) |

---

## 1. Current state — what the codebase already gives F11

### 1.1 Engram is the only "MCP-style" integration, and it is NOT MCP

`app/core/engram_client.py` (65 lines) is a hand-rolled urllib client against the Engram HTTP API. It hits plain REST endpoints (`/sessions`, `/observations`, `/context`), **not** the Model Context Protocol. There is no `mcp` package, no `langchain-mcp-adapters`, no `langgraph` in `requirements.txt` (verified at HEAD `d139c9e`). The repo has never used the MCP wire protocol.

Key surface (`app/core/engram_client.py`):

```python
class EngramClient:
    def __init__(self, base_url: str | None = None, timeout: float = 3.0):
        self.base_url = (base_url or os.getenv("ENGRAM_URL", "http://localhost:7437")).rstrip("/")
    # create_session, end_session, save_observation, get_context — all use stdlib urllib.
```

Engram is consumed in only one user-facing place that resembles a "tool": `app/core/llm_validator.py` (model-list cache, lines 105–223), passed in as `engram_client=` for tests. **It is not exposed to the chat agent today** — `app/api/chat.py` does not import `EngramClient`.

### 1.2 There is no LangChain agent — `chat.py` is a direct LLM call with prompt-injected RAG

`app/api/chat.py` is the entire chat surface. The streaming path is:

```python
# line 121–186, paraphrased
handler = SSEStreamCallbackHandler()
async def event_generator():
    docs, rag_context = await retrieve_context()
    prompt = (
        "Eres un asistente de arquitectura de software. ...\n"
        f"Contexto recuperado desde RAG:\n{rag_context or 'No se encontro contexto relevante.'}\n\n"
        f"Mensaje del usuario: {body.message}"
    )
    async for event in model.astream(prompt):
        if event.content:
            yield f"event: token\ndata: {json.dumps(event.content, ensure_ascii=False)}\n\n"
    yield "event: done\ndata: null\n\n"
```

No `create_react_agent`, no `create_agent`, no `ToolNode`, no `bind_tools`, no `messages` state — confirmed by `git ls-files | grep -E "agent|tool|mcp"` returning empty. RAG context is pasted into the prompt; the LLM has no tool-use loop. **Adding Context7 requires introducing an actual agent runtime, not just a client.**

### 1.3 Langfuse is NOT wired in `app/`

The preflight said "Langfuse is already wired for tracing on the backend (see app/core/langfuse_tracer.py or similar)". This is **incorrect at HEAD `d139c9e`**:

- `git ls-files | grep -E "langfuse|tracer|tracing"` → empty.
- `grep -rE "tracer|tracing|CallbackHandler|observe\("` over the whole repo → only matches `SSEStreamCallbackHandler` (token streaming, not Langfuse).
- `app/core/` has no `langfuse_*.py` file.
- ADR-004 (`docs/adr/004-langfuse.md`) declares Langfuse **accepted** and lists the 5 langfuse-* services in compose, but the wiring was never landed in code.
- `.env.example` (lines 28–41) and `docker-compose.yml` (lines 137–181) already declare keys/services.

**Net effect on F11:** the third acceptance criterion (`Trazas registradas en Langfuse`) cannot be satisfied without also landing Langfuse integration in the same change. This must be a first-class sub-task of F11 (or split into F12, with F11 explicitly deferring tracing).

### 1.4 Existing docker-compose MCP pattern (the `engram` + `engram-proxy` sidecar)

`docker-compose.yml` already documents the local-sidecar pattern (`alpine/socat:1.8.1.3`):

```yaml
# line 83–111
engram:
  image: ghcr.io/gentleman-programming/engram:latest
  command: serve 7438
  ports:
    - "7439:7437"   # host:container — note the port remap

engram-proxy:
  image: alpine/socat:1.8.1.3
  network_mode: service:engram
  command: TCP-LISTEN:7437,fork,reuseaddr TCP:127.0.0.1:7438
  depends_on:
    engram:
      condition: service_started
```

The backend then talks to engram at `http://engram:7437` via the `ENGRAM_URL` env var (`docker-compose.yml:48` and `app/core/engram_client.py:17`). This is the precedent for any future local MCP server: image + sidecar (only if stdio is required).

### 1.5 Backend image is Python-only — no Node.js, no `npx`

`backend/Dockerfile` is a multi-stage build with `FROM python:3.11-slim`. Runtime stage installs only `libpq5` + `curl`. The build context is `.` (repo root), so anything added to `app/`, `requirements.txt`, or `backend/` is part of the rebuild. A stdio-based MCP server via `npx -y @upstash/context7-mcp` cannot run in this image — it would either need Node added (~+200MB, package manager conflicts) **or** a sidecar container (the `engram-proxy` pattern, but with Node).

### 1.6 `.env.example` already reserves `CONTEXT7_API_KEY=`

Line 98 of `.env.example`:

```bash
# ----------------------------------------------------------------------------
# MCPs — API keys opcionales
# ----------------------------------------------------------------------------
CONTEXT7_API_KEY=
WEB_SEARCH_API_KEY=
```

`README.md:135` documents it: `| CONTEXT7_API_KEY | API key para Context7 MCP | (opcional) |`. The slot is reserved, the value is intentionally empty (free-tier default).

### 1.7 ADR-007 already prescribes the integration shape

`docs/adr/007-six-mcps.md` line 76 prescribes `transport: http` to `https://mcp.context7.com/mcp` as the official Context7 MCP server URL. ADR-001 line 34 names `MultiServerMCPClient` (from `langchain-mcp-adapters`) as the intended bridge from MCP servers to the LangChain agent. **F11 is the first change to implement either ADR.**

---

## 2. Context7 protocol surface (authoritative, verified against the source repo)

Sources: `github.com/upstash/context7` README, `pypi.org/project/langchain-mcp-adapters`, MCP spec 2025-03-26.

### 2.1 MCP server URL

`https://mcp.context7.com/mcp` (HTTP streamable transport, per Context7 README; the preflight's `https://mcp.context7.com/sse` is the legacy endpoint and not what the README's official Cursor install badge uses).

### 2.2 Tools exposed (exactly 2)

| Tool | Required args | Purpose |
|---|---|---|
| `resolve-library-id` | `query: string`, `libraryName: string` | Resolve a fuzzy library name → Context7 ID (`/org/project` slash-id). |
| `query-docs` | `libraryId: string` (slash-id), `query: string` | Fetch up-to-date docs/code snippets for that library. |

> **Naming note for the proposal:** the orchestrator preflight called the second tool `get-library-docs`. The current source name is `query-docs`. This is a known Context7 API rename history (previously `get-library-docs`, then `query-docs`). Pin to `query-docs` and document the rename in the spec.

### 2.3 Authentication

- **Free tier:** works without an API key, rate-limited.
- **Authenticated:** set `Authorization: Bearer ${CONTEXT7_API_KEY}` on every HTTP request. Context7 README explicitly recommends a key for higher rate limits.
- `langchain-mcp-adapters` 0.3.2 (latest as of 2026-08-06, MIT, Python ≥3.10) passes runtime headers via `headers={}` on `MultiServerMCPClient` entries for `sse` and `http` transports.

### 2.4 Transport options that `MultiServerMCPClient` supports for Context7

```python
# HTTP to Upstash-hosted — preferred, no infra cost
{"context7": {
    "transport": "http",                                     # or "streamable_http"
    "url": "https://mcp.context7.com/mcp",
    "headers": {"Authorization": f"Bearer {os.getenv('CONTEXT7_API_KEY', '')}"},
}}

# Stdio to a locally-installed npm package — would need a sidecar
{"context7": {
    "transport": "stdio",
    "command": "npx",
    "args": ["-y", "@upstash/context7-mcp"],
}}
```

Other transports (`sse`, `websocket`) are supported by the adapter but not used by Context7 today.

### 2.5 Error semantics the proposal must plan around

From `langchain-mcp-adapters` docs:

- **Tool execution error** (`isError=True` from MCP) → returned to the model as `ToolMessage(status="error")` so the agent can self-correct. Default `handle_tool_errors=True`.
- **Transport/session failure** → raises. Must be caught at the agent loop boundary; otherwise it bubbles to the SSE `event: error`.
- **Rate limit (HTTP 429)** from Upstash → transport failure, must be retried with backoff or surfaced as "Context7 temporalmente no disponible" so the agent can fall back to its training data + RAG.

---

## 3. Open questions for the proposal phase (must be resolved before apply)

1. **Agent runtime shape.** `langchain.agents.create_agent` (newer, simpler, fewer lines) vs `langgraph.graph.StateGraph` + `ToolNode` + `tools_condition` (matches ADR-001's `MultiServerMCPClient` reference, more explicit, easier to extend with the other 5 MCPs). Decision shapes the rest of F11.
2. **Langfuse wiring scope.** Inline `langfuse.langchain.CallbackHandler` as a sub-task of F11, or split into F12 "Langfuse observability" and let F11 ship without the third acceptance criterion?
3. **Where does the agent live?** Refactor `app/api/chat.py` in place, or extract to a new `app/core/agent.py` / `app/agents/architect_agent.py` that `chat.py` calls? The latter keeps the route thin and matches ADR-001's "framework del agente" wording.
4. **Where does the Context7 client wrapper live?** `app/core/context7_client.py` (parallel to `engram_client.py`) vs `app/mcp/context7.py` (new namespace) vs inside `app/core/agent.py` (no wrapper). For a single-transport HTTP call, a thin wrapper is overkill unless we want a stub for tests.
5. **Tool surface after integration.** Is the agent only given Context7's two tools, or also exposed to Engram (`save_observation`, `get_context`) so it can write/read memories on demand? ADR-005 implies yes; current code does not.
6. **RAG + Context7 precedence.** Today RAG context is *inlined into the prompt*. With tools, Context7 would compete with RAG for the same context window slot. Does the agent choose, or do we pre-decide (e.g., RAG always-on, Context7 only when the user says "use context7" or asks about a specific library)?
7. **Streaming UX.** `agent.astream_events(...)` vs `agent.astream({"messages": ...})` vs the current `model.astream(prompt)` — the SSE pipeline in `app/api/sse.py:24` (`on_llm_new_token`) expects a `BaseCallbackHandler`. Tool calls produce additional events (`on_tool_start`, `on_tool_end`) that the frontend does not currently render. Scope of SSE event surface change?
8. **Tests.** Existing convention is `unittest.mock.patch("module.urlopen")` for HTTP clients (see `tests/test_engram_client.py:16–43`) and `pytest` for the chat endpoint (`tests/api/test_chat.py`). New tests must use the same convention; can they use a recorded fixture from Context7, or do we mock `MultiServerMCPClient` at the `client.get_tools()` boundary?
9. **Cost & rate limits.** Without a key, what is the free-tier limit (Context7 docs do not publish a number)? Decision: ship without key, log 429s, document the upgrade path; or require key for production?
10. **Outbound network from `backend` container.** `docker-compose.yml:18` declares the default network. Egress to `https://mcp.context7.com` is implicit (Docker default network allows outbound). Confirm no firewall/proxy in target environments (CI, demo VM) blocks it.

---

## 4. Alternatives considered

### 4.1 Alternative A — Public HTTPS to Upstash-hosted Context7 (ADR-007's choice)

```yaml
# no docker-compose change required — backend talks to public URL over HTTPS
CONTEXT7_API_KEY: ""  # free tier
```

```python
# app/core/context7_client.py (sketch)
from langchain_mcp_adapters.client import MultiServerMCPClient
client = MultiServerMCPClient({
    "context7": {
        "transport": "http",
        "url": "https://mcp.context7.com/mcp",
        "headers": {"Authorization": f"Bearer {os.getenv('CONTEXT7_API_KEY', '')}"},
    },
})
tools = await client.get_tools()
```

| Aspect | Detail |
|---|---|
| **Pros** | Zero new infra. Matches ADR-007. `langchain-mcp-adapters` supports it out of the box with runtime headers. No image bloat. Network egress is the only new dependency. |
| **Cons** | Outbound dependency on `mcp.context7.com`. Free tier rate-limited. API key optional but recommended. |
| **Effort** | Low (1 file in `app/core/`, 2-line requirements bump, env wiring). |
| **Risk** | Upstash outage = Context7 tools unavailable → agent falls back to training + RAG (must be designed for). |

### 4.2 Alternative B — Local stdio sidecar (`@upstash/context7-mcp` via `npx`)

```yaml
# docker-compose.yml addition
context7-mcp:
  image: node:20-alpine
  command: npx -y @upstash/context7-mcp
  # no port needed — stdio transport, attached by MultiServerMCPClient via command/args
```

```python
client = MultiServerMCPClient({
    "context7": {
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@upstash/context7-mcp"],
    },
})
```

| Aspect | Detail |
|---|---|
| **Pros** | No external dependency. Predictable latency on local Docker network. No API key. |
| **Cons** | Adds a Node.js container to the stack (currently zero Node images — only Python + Postgres + ClickHouse + MinIO + Redis + Nginx + Langfuse). Cold start penalty per call (`npx` resolves packages every time unless we pre-bake). npx + network access inside the container. Diverges from ADR-007's `transport: http` decision. |
| **Effort** | Medium (new service in compose, Dockerfile for the sidecar, pre-bake step, restart policies). |
| **Risk** | Supply-chain risk on `@upstash/context7-mcp` npm package. Local resource usage grows. |

### 4.3 Recommendation

**Alternative A (public HTTPS).** Rationale:

1. ADR-007 already chose it.
2. ADR-001 already named `MultiServerMCPClient`, which supports `transport: http` natively.
3. Zero new infra services; preserves the 11-service stack ceiling.
4. `requirements.txt` change is minimal (`langchain-mcp-adapters>=0.3.2`, `mcp>=1.0`).
5. Backend image stays Python-only.
6. `.env.example:98` already declares `CONTEXT7_API_KEY=` — drop-in.
7. Local stdio sidecar remains an option later if Upstash's SLA or pricing becomes a blocker; the wrapper client interface would be the same.

---

## 5. Risks

1. **No LangChain agent exists today.** F11 cannot bolt Context7 onto the current `model.astream(prompt)` path; it must introduce an agent runtime (`create_agent` or `StateGraph`). This is a bigger architectural lift than the issue title suggests. (Mitigation: call it out in the proposal; consider whether to split "agent runtime" from "Context7 wiring".)
2. **Langfuse tracing is not wired.** The third acceptance criterion (`Trazas registradas en Langfuse`) is unachievable without also wiring `langfuse.langchain.CallbackHandler` — currently zero Langfuse code in `app/`. The preflight assertion was wrong. (Mitigation: make Langfuse wiring an explicit F11 task with its own acceptance scenario.)
3. **Rate-limit / outage of public endpoint.** Free tier throttling and Upstash outages translate to `ToolMessage(status="error")` or transport exceptions. Without a clear fallback policy the agent may loop or return empty answers. (Mitigation: catch transport errors at the agent boundary, emit a degraded-context warning, log to Langfuse when wired.)
4. **Tool name drift.** Context7 renamed `get-library-docs` → `query-docs` at some point. The proposal must pin the exact current tool name with a regression test against the live server (or a recorded fixture). (Mitigation: spec scenario must assert both tool names exist.)
5. **RAG vs Context7 context bloat.** Both inject documentation into the conversation; without a rule the agent can over-fetch and blow the model's context window, especially on small local models (Ollama `llama3`, LM Studio defaults). (Mitigation: cap `k` for both retrieval paths; consider a heuristic "prefer RAG unless the user names a library".)
6. **Backend image rebuild.** Any `requirements.txt` change triggers the multi-stage backend rebuild (~5–8 min cold cache per `backend/Dockerfile:25`). Acceptable but not free. (Mitigation: verify `langchain-mcp-adapters` is a pure-Python wheel with no torch dep — it is, per its PyPI page — so rebuild stays inside the existing cacheable layer.)
7. **API key leakage.** `CONTEXT7_API_KEY` will live in `.env` and be passed to the backend container via `env_file`. Same risk posture as existing `LANGFUSE_SECRET_KEY`, `ENCRYPTION_KEY`. (Mitigation: confirm `.gitignore` excludes `.env` — verified, line ~30 of `.gitignore`.)
8. **Egress blocking in CI / demo environments.** Sandbox or demo VMs may block outbound `mcp.context7.com`. CI tests would silently skip Context7 paths. (Mitigation: an integration test must guard with `@pytest.mark.skipif(not os.getenv("CONTEXT7_API_KEY"), reason="no key")` and a `requests.head` health probe in `setup-local.sh`.)

---

## 6. References

### Code paths verified at HEAD `d139c9e`

- `app/core/engram_client.py` (65 LOC, urllib-based, NOT MCP)
- `app/api/chat.py` (197 LOC, direct `model.astream(prompt)` with RAG-injected prompt; no agent, no tools)
- `app/core/llm_loader.py` (`build_langchain_model`, `init_chat_model` from `langchain.chat_models`)
- `app/api/sse.py` (`SSEStreamCallbackHandler` — only callback in the repo)
- `app/core/llm_validator.py` (lines 105–223 — the only consumer of `EngramClient`)
- `app/core/embeddings.py` (lines 16, 39 — only `lru_cache` matches for "tool" substring via `functools`)
- `backend/Dockerfile` (multi-stage, Python 3.11-slim, no Node.js)
- `docker-compose.yml` (lines 83–111 engram+engram-proxy sidecar pattern; lines 137–181 langfuse stack declared but unwired)
- `requirements.txt` (20 lines, no `mcp`, no `langchain-mcp-adapters`, no `langgraph`, no `langfuse`)
- `tests/test_engram_client.py` (43 LOC, `unittest.mock.patch("app.core.engram_client.urlopen")` convention)
- `tests/api/test_chat.py` (109 LOC, `pytest` + SSE format assertions, JWT auth tests)
- `.env.example` (line 98: `CONTEXT7_API_KEY=` reserved)
- `scripts/setup-local.sh` (180 LOC, end-to-end local bootstrap; would need a Context7 health probe added)

### ADRs

- `docs/adr/001-langchain-framework.md` — names `MultiServerMCPClient` as the bridge (line 34)
- `docs/adr/004-langfuse.md` — declares Langfuse accepted but does not document the wiring gap
- `docs/adr/005-engram-mcp.md` — precedent for the "memoria como servicio" pattern
- `docs/adr/007-six-mcps.md` — prescribes `transport: http` to `https://mcp.context7.com/mcp` for Context7

### External (authoritative)

- Context7 platform: https://context7.com · source: https://github.com/upstash/context7
- MCP tool surface (`resolve-library-id`, `query-docs`): Context7 README §"Available Tools"
- `langchain-mcp-adapters` 0.3.2 on PyPI: https://pypi.org/project/langchain-mcp-adapters/ — `MultiServerMCPClient`, transports `stdio` / `http` / `sse` / `streamable_http`, runtime `headers=`, `handle_tool_errors` default
- MCP transports spec: https://modelcontextprotocol.io/specification/2025-03-26/basic/transports#streamable-http

### Issue

- #13 — [F11] Context7 MCP integrado — https://github.com/danielCH26/arch-agent/issues/13
