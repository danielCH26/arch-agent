# Proposal: F11 — Context7 MCP Integration

| Field | Value |
|---|---|
| Change slug | `F11-context7-mcp` |
| Branch | `feature/F11-context7-mcp` |
| Base SHA | `d139c9e` (`origin/development`, post-merge of PR #64) |
| GitHub issue | [#13 — [F11] Context7 MCP integrado](https://github.com/danielCH26/arch-agent/issues/13) |
| Related ADRs | ADR-001 (LangChain framework), ADR-004 (Langfuse observability), ADR-005 (Engram MCP), ADR-007 (six MCPs) |
| ADR to add | ADR-010 (Context7 transport & agent runtime shape) |
| Engram topic_key | `sdd/F11-context7-mcp/proposal` |
| Phase | `sdd-propose` |
| Artifact store | hybrid (OpenSpec + Engram) |

---

## 1. Why

GitHub issue **#13** requires the chat assistant to look up up-to-date library documentation through the Context7 MCP server, surface relevant results, and log every invocation to Langfuse. Verified at HEAD `d139c9e`, the repo currently has **no LangChain agent** (`app/api/chat.py:182` calls `model.astream(prompt)` directly) and **no Langfuse code in `app/`** (`grep -rE "CallbackHandler"` only matches the SSE token handler in `app/api/sse.py:7`). F11 must therefore introduce the agent runtime AND wire Langfuse AND add Context7 in one atomic change — splitting it would leave Context7 without a consumer or leave the issue's third acceptance criterion (`Trazas registradas en Langfuse`) unmet.

## 2. What changes

- **Backend (NEW + MODIFIED):** introduce a LangChain `create_agent` runtime in `app/core/agent.py`; add `app/core/context7_mcp.py` with the `MultiServerMCPClient` config block; add `app/core/langfuse_tracer.py` wiring `langfuse.langchain.CallbackHandler`; refactor `app/api/chat.py` to invoke the agent instead of `model.astream(prompt)`; extend `app/api/sse.py` to surface tool events (`on_tool_start`, `on_tool_end`) without breaking the existing token stream.
- **Configuration:** bump `requirements.txt` to add `langchain-mcp-adapters==0.3.2`, `mcp>=1.0`, `langfuse>=2.0.0`. `.env.example:98` already reserves `CONTEXT7_API_KEY=` — no new env required.
- **Infrastructure:** **no `docker-compose.yml` change.** Backend reaches `https://mcp.context7.com/mcp` over HTTPS from the default network (ADR-007 §Implementación line 76). No Node.js sidecar; image stays Python-only.
- **Tests (NEW):** `tests/core/test_context7_mcp.py` (recorded fixture + live-server integration gated by `CONTEXT7_API_KEY`); `tests/core/test_agent.py` (mocked `MultiServerMCPClient.get_tools`); extend `tests/api/test_chat.py` with tool-event assertions.
- **Frontend:** none. SSE event surface gains `tool_start`/`tool_end` events that the current Chainlit frontend ignores.

## 3. Approach chosen

1. Build the LangChain chat model via the existing `build_langchain_model(user_id)` factory (`app/core/llm_loader.py`) — keeps per-user LLM config intact.
2. Initialize `MultiServerMCPClient` once at app startup in `app/core/context7_mcp.py` with a single `context7` server entry (`transport: http`, `url: https://mcp.context7.com/mcp`, runtime `Authorization` header when `CONTEXT7_API_KEY` is set). Expose `await get_context7_tools()` → list of LangChain `BaseTool`.
3. Construct the agent with `langchain.agents.create_agent(model, tools=[...context7_tools], system_prompt=..., middleware=[])` (LangChain ≥ 0.3 modern API; ADR-001 alignment).
4. Pass `callbacks=[SSEStreamCallbackHandler(), langfuse_handler()]` to the agent's `astream_events(...)` invocation so tokens AND tool events flow through the existing SSE pipeline.
5. RAG context stays injected into the system prompt (unchanged), preserving the existing `_doc_to_source` SSE `sources` event for the frontend.

## 4. Out of scope (v1)

- Wiring the other 5 MCPs (Filesystem, Puppeteer, Web Search, Fetch — ADR-007 deferral). F11 ships Context7 only; the `MultiServerMCPClient` is built extensible so future MCPs are config-only.
- Switching the chat pipeline's streaming model selector (`app/core/llm_model_selector.py`) — agent uses the same per-user LLM the route already builds.
- Frontend UI changes — Chainlit continues ignoring unknown SSE events.
- Replacing `app/core/engram_client.py` with a real MCP client — out of F11 (ADR-005 already names Engram as MCP but Engram is currently REST; deferred).
- `langgraph` adoption — `create_agent` is sufficient and lighter; StateGraph is reserved for a future MCP-heavy change.
- A separate ADR for Langfuse wiring — folded into ADR-010 to keep the ADR count small.

## 5. Resolved ambiguities

1. **Agent runtime shape → `langchain.agents.create_agent`.** Rationale: official modern API, ~50 fewer LoC than StateGraph+ToolNode, supports `callbacks=` natively, and matches ADR-001's "framework del agente" framing.
2. **Tool surface → exactly `resolve-library-id` and `query-docs`.** Rationale: pins to current Context7 upstream names (rename history: `get-library-docs` → `query-docs`); bound via `await client.get_tools()`; the LLM decides when to invoke based on tool descriptions.
3. **RAG vs Context7 precedence → RAG always-on (system prompt), Context7 on demand (tool).** Rationale: RAG is cheap, deterministic, and proprietary; Context7 is for external library docs only. Heuristic pre-warm: if prompt contains `/lib|framework|sdk|api|docs/i` OR mentions a recognized library, the system prompt hints the agent to call Context7.
4. **Langfuse scope → inline within F11 (atomic).** Rationale: per user decision — without Langfuse wiring the third AC is unmet and splitting into F12 would leave F11 broken. Lives in `app/core/langfuse_tracer.py`, returns `langfuse.langchain.CallbackHandler` when env vars are set, `None` when unset (degrades gracefully).
5. **Auth → free-tier default, opt-in key.** Rationale: `.env.example:98` reserves `CONTEXT7_API_KEY=` already empty; pass `Authorization: Bearer ${key}` only when the env var is non-empty.
6. **Error handling → graceful degrade to RAG-only.** Rationale: 5s per-tool timeout; transport failures caught at agent boundary → yield `event: degraded\ndata: {"source":"context7"}\n\n` then continue with RAG context only. `ToolMessage(status="error")` (MCP `isError=true`) is handled by the agent's default `handle_tool_errors=True`.
7. **Tool name pinning → `resolve-library-id` and `query-docs`, recorded fixture.** Rationale: `langchain-mcp-adapters==0.3.2` pinned exactly; tests assert both names exist via `client.get_tools()` against a recorded fixture (offline) and against the live server (`@pytest.mark.skipif(not os.getenv("CONTEXT7_API_KEY"))`).
8. **Context budget → RAG `k≤5` (existing), Context7 result truncated to 4000 chars before merging.** Rationale: protects Ollama `llama3` (8k ctx). Context7 wins for library docs, RAG wins for patterns; merge order = system prompt (Context7) before user prompt (RAG).
9. **Docker-compose → no change.** Rationale: ADR-007 line 76 already chose public HTTPS; backend image stays Python-only; avoids adding Node.js or a socat sidecar.
10. **Dependency pin → `langchain-mcp-adapters==0.3.2`, `mcp>=1.0`, `langfuse>=2.0.0`.** Rationale: exact pin on the adapter (small surface, API drift risk), lower bound on `mcp` and `langfuse` (their APIs are stable across the version range we consume).

## 6. Affected components (HEAD `d139c9e`)

| Area | Impact | Description |
|---|---|---|
| `app/core/agent.py` | **NEW** | LangChain `create_agent` factory + `run_agent(...)` async entrypoint. |
| `app/core/context7_mcp.py` | **NEW** | `MultiServerMCPClient` singleton + `get_context7_tools()` async helper. |
| `app/core/langfuse_tracer.py` | **NEW** | `get_langfuse_handler()` factory returning `CallbackHandler` or `None`. |
| `app/api/chat.py` | **MODIFIED** | Replace `model.astream(prompt)` with `agent.astream_events(...)`; keep RAG prompt-injection + `sources` event. |
| `app/api/sse.py` | **MODIFIED** | Add `on_tool_start` / `on_tool_end` → `event: tool_start` / `event: tool_end` (frontend-agnostic). |
| `app/core/llm_loader.py` | UNCHANGED | Reused as-is. |
| `requirements.txt` | **MODIFIED** | + `langchain-mcp-adapters==0.3.2`, `mcp>=1.0`, `langfuse>=2.0.0`. |
| `.env.example` | UNCHANGED | `CONTEXT7_API_KEY=` slot already present at line 98. |
| `docker-compose.yml` | UNCHANGED | No new service. |
| `tests/core/test_context7_mcp.py` | **NEW** | Recorded-fixture + live-server tests. |
| `tests/core/test_agent.py` | **NEW** | Mocked `MultiServerMCPClient.get_tools`, tool-call routing. |
| `tests/api/test_chat.py` | **MODIFIED** | New assertions for `tool_start` / `tool_end` SSE events. |
| `docs/adr/010-context7-agent-runtime.md` | **NEW** | ADR for transport choice + runtime shape + Langfuse wiring. |

## 7. Stack dependency

F11 branches from `origin/development @ d139c9e` (post-merge of PR #64). **No cross-dependencies on open PRs.** PR #64 is already merged into the base branch.

## 8. Capabilities (contract for `sdd-spec`)

### New Capabilities
- `context7-mcp-integration`: MCP client config, tool surface (`resolve-library-id`, `query-docs`), auth header handling, transport failure semantics. Each becomes `openspec/specs/context7-mcp-integration/spec.md`.
- `agent-runtime`: LangChain `create_agent` factory, tool-binding, system prompt assembly, callback wiring. Each becomes `openspec/specs/agent-runtime/spec.md`.
- `langfuse-tracing`: `CallbackHandler` factory, env-driven enable/disable, trace lifecycle. Each becomes `openspec/specs/langfuse-tracing/spec.md`.

### Modified Capabilities
None (no prior `openspec/specs/` exists at `d139c9e`).

## 9. Success criteria

### AC1 — El agente puede consultar documentación via Context7
- **Given** an authenticated user with a configured LLM (`POST /api/llm/config`) and a chat prompt that names an external library (e.g. `"¿cómo configuro retries en la librería requests?"`)
- **When** `POST /api/chat` is called
- **Then** the agent calls `resolve-library-id` followed by `query-docs`, the SSE stream emits `event: tool_start` and `event: tool_end` for each call, and the final `event: done` follows a response grounded in the returned docs.

### AC2 — Resultados de búsqueda son relevantes
- **Given** the same setup
- **When** the prompt is a generic architecture question (no library mention)
- **Then** the agent MAY skip Context7 and rely on RAG; when Context7 IS called, the result text MUST contain at least one code or doc fragment from the resolved library.

### AC3 — Trazas registradas en Langfuse
- **Given** Langfuse env vars (`LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`) are set
- **When** any `/api/chat` call completes (success OR tool error OR degradation)
- **Then** a trace with `user_id`, `project_id`, model name, tool call names, token counts, and latency appears in Langfuse UI (`http://localhost:3000`).

### Negative path
- **Given** `https://mcp.context7.com/mcp` is unreachable (timeout 5s)
- **When** `/api/chat` is called
- **Then** the agent emits `event: degraded\ndata: {"source":"context7"}\n\n`, then continues answering using RAG context only, and the response still arrives within the existing latency budget.

## 10. Risks and mitigations

| # | Risk | Likelihood | Mitigation |
|---|---|---|---|
| 1 | Agent runtime introduces regressions in existing chat behavior. | Med | Spec includes a parity scenario: identical prompt → identical `sources` event + token stream (modulo tool events). |
| 2 | Langfuse env unset → silent failure or import error. | High | `get_langfuse_handler()` returns `None` when keys missing; agent runs without tracing (logged at WARNING). |
| 3 | Context7 tool name drift. | Med | Exact version pin + recorded fixture asserting both `resolve-library-id` and `query-docs` exist. |
| 4 | Context7 outage / 429. | Med | 5s timeout, `event: degraded` warning, agent continues with RAG (success criteria §9 negative path). |
| 5 | Context budget blow on small local models. | High | RAG `k≤5` (existing); Context7 result truncated to 4000 chars. |
| 6 | `requirements.txt` bump → backend image rebuild. | Low | `langchain-mcp-adapters` is pure-Python wheel; no torch/system deps. |
| 7 | `CONTEXT7_API_KEY` leakage. | Low | `.gitignore` already excludes `.env`; same posture as `LANGFUSE_SECRET_KEY`. |
| 8 | Outbound `mcp.context7.com` blocked in CI/demo VM. | Med | `@pytest.mark.skipif(not CONTEXT7_API_KEY)` gates live test; fixture-based test covers offline CI. |
| 9 | **NEW** Dual tool-call latency on small models. | Med | System prompt instructs the agent to call `resolve-library-id` ONLY when a library is named; otherwise skip Context7 to keep first-token latency low. |
| 10 | **NEW** LangChain `create_agent` API churn across versions. | Low | Pin `langchain>=0.3,<0.4` floor in `requirements.txt` to lock the modern API surface. |

## 11. Rollback plan

Revert the F11 commits on `feature/F11-context7-mcp`. Because F11 is additive (new files in `app/core/`, additive env vars, additive deps), the revert restores `app/api/chat.py` to the direct-`model.astream(prompt)` flow without touching docker/.env. No data migration, no Langfuse schema change. Required revert commits are confined to the F11 branch — `origin/development` is untouched.

## 12. Delivery plan (chained PRs expected)

Estimated total: **~1500–2000 LoC** across backend + tests. `delivery_strategy: auto-chain` + `chain_strategy: stacked-to-main` is already cached. Forecast: `400-line budget risk: High` → **chained PRs required**.

Planned slices (each ≤400 changed lines, autonomous, with tests + verification):

1. **PR F11.1 — Scaffold + deps** (~250 LoC). Add `langchain-mcp-adapters==0.3.2`, `mcp>=1.0`, `langfuse>=2.0.0`; new empty modules `app/core/agent.py`, `app/core/context7_mcp.py`, `app/core/langfuse_tracer.py` with public function signatures + type stubs; tests importable but skipped. Targets `feature/F11-context7-mcp`.
2. **PR F11.2 — Context7 MCP client + tools** (~350 LoC). Implement `MultiServerMCPClient` config + `get_context7_tools()`; recorded-fixture tests + live-server tests; ADR-010 merged first (docs-only). Targets `feature/F11-context7-mcp`.
3. **PR F11.3 — LangChain agent runtime + Langfuse wiring** (~500 LoC, will be split further if needed). `create_agent` factory + `run_agent()` + `get_langfuse_handler()`; mocked agent tests. Targets `feature/F11-context7-mcp`.
4. **PR F11.4 — `app/api/chat.py` refactor + SSE tool events** (~400 LoC). Replace `model.astream(prompt)` with `run_agent`; extend `SSEStreamCallbackHandler` with `on_tool_start` / `on_tool_end`; extend `tests/api/test_chat.py`. Targets `feature/F11-context7-mcp`.

Each PR carries its own tests, ADR reference, and rollback boundary. Chained-PR order = 010-ADR → 1 → 2 → 3 → 4; `sdd-tasks` will refine the exact line budget per PR.

## 13. ADRs to add

- **ADR-010 — Context7 transport & agent runtime shape** (mandatory). Records: (a) `transport: http` to `https://mcp.context7.com/mcp` (re-affirms ADR-007); (b) `langchain.agents.create_agent` as the runtime (over StateGraph for v1); (c) Langfuse wiring scope = inline within F11 (atomic); (d) `MultiServerMCPClient` singleton in `app/core/context7_mcp.py`; (e) tool name pin to current upstream.

No second ADR for Langfuse — folded into ADR-010 to keep the ADR count small per the proposal rule.

## 14. References

- `openspec/changes/F11-context7-mcp/explore.md` (just completed; Engram `sdd/F11-context7-mcp/explore`).
- `docs/adr/001-langchain-framework.md` — names `MultiServerMCPClient`.
- `docs/adr/004-langfuse.md` — declares Langfuse accepted (but unwired until F11).
- `docs/adr/005-engram-mcp.md` — precedent for MCP integration patterns.
- `docs/adr/007-six-mcps.md` — prescribes `transport: http` to Context7.
- Issue #13 — https://github.com/danielCH26/arch-agent/issues/13
- Context7 docs: https://github.com/upstash/context7
- `langchain-mcp-adapters` 0.3.2: https://pypi.org/project/langchain-mcp-adapters/
