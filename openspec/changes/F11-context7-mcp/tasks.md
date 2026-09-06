# Tasks: F11 — Context7 MCP Integration

| Field | Value |
|---|---|
| Change slug | `F11-context7-mcp` |
| Capability | `context7-mcp-integration` (NEW) |
| Branch | `feature/F11-context7-mcp` (DO NOT switch) |
| Base | `origin/development` @ `d139c9e` (PR #64 merged) |
| HEAD at planning time | `72b1b21` (F11 design), working tree clean |
| Spec | `openspec/specs/context7-mcp-integration/spec.md` @ `223f7b4` (10 REQ, 8 SCN) |
| Design | `openspec/changes/F11-context7-mcp/design.md` @ `72b1b21` (17 sections, 4 SD) |
| Engram topic_key | `sdd/F11-context7-mcp/tasks` |
| Phase | `sdd-tasks` |
| Artifact store | hybrid (OpenSpec file + Engram upsert) |
| Issue | [#13](https://github.com/danielCH26/arch-agent/issues/13) |

Relationship to prior phases: this file adds **no new decisions**. It converts `design.md` §2 (component inventory), §6 (signatures), §12 (slice seams) and §13 (test strategy) into ordered, one-session tasks, and applies the two mandatory sub-splits called out in `design.md` §17 (F11.3 → F11.3a/b, F11.4 → F11.4a/b).

LoC convention: **LoC = authored source lines (added + modified) in `app/`, `requirements.txt`.** Test LoC is tracked separately. `openspec/`, `docs/adr/` and README are NOT counted against the budget.

---

## 1. Forecast summary

Decision needed before apply: No
Chained PRs recommended: Yes
Chain strategy: stacked-to-main
400-line budget risk: Low

| Slice | Task | Prod LoC | Test LoC | REQ / SCN | Target test files |
|---|---|---|---|---|---|
| **F11.0** docs-only | 1.1 README env block | 0 | 0 | — | — |
| | 1.2 openspec artifact sync | 0 | 0 | — | — |
| | **slice total** | **0** | **0** | | |
| **F11.1** deps + stubs | 2.1 `requirements.txt` pins | 4 | 0 | REQ-1 | — |
| | 2.2 `context7_mcp.py` stub | 30 | 0 | REQ-2 | — |
| | 2.3 `agent.py` stub | 55 | 0 | REQ-3 | — |
| | 2.4 `langfuse_tracer.py` stub | 25 | 0 | REQ-5 | — |
| | 2.5 three import-smoke tests | 6 | 90 | REQ-9 | `tests/core/test_context7_mcp.py`, `test_agent.py`, `test_langfuse_tracer.py` |
| | **slice total** | **120** | **90** | | **≈210 changed** |
| **F11.2** MCP client | 3.1 `build_context7_client()` | 45 | 0 | REQ-2 / SCN-4, SCN-5 | — |
| | 3.2 `get_context7_tools()` + 5s timeout | 40 | 0 | REQ-2, REQ-6 | — |
| | 3.3 recorded tool-name fixture | 0 | 30 | SCN-8 | `tests/fixtures/context7_tools.py` |
| | 3.4 client unit tests + live-gated test | 0 | 180 | REQ-2, REQ-6, REQ-9 / SCN-4, SCN-5, SCN-8 | `tests/core/test_context7_mcp.py` |
| | **slice total** | **85** | **210** | | **≈295 changed** |
| **F11.3a** agent factory | 4.1 `format_rag_context()` | 45 | 0 | REQ-3, REQ-8 | — |
| | 4.2 `build_agent()` | 45 | 0 | REQ-3 | — |
| | 4.3 `run_agent()` stream + degraded path | 90 | 0 | REQ-4, REQ-6, REQ-8 / SCN-3 | — |
| | 4.4 agent unit tests | 0 | 160 | REQ-3, REQ-8 / SCN-1(part), SCN-2 | `tests/core/test_agent.py` |
| | **slice total** | **180** | **160** | | **≈340 changed** |
| **F11.3b** Langfuse | 5.1 `get_langfuse_handler()` + `_env_present()` | 50 | 0 | REQ-5 / SCN-6 | — |
| | 5.2 trace-name wiring in `run_agent` | 20 | 0 | REQ-5 / SCN-7 | — |
| | 5.3 tracer unit tests | 0 | 70 | REQ-5, REQ-9 / SCN-6 | `tests/core/test_langfuse_tracer.py` |
| | **slice total** | **70** | **70** | | **≈140 changed** |
| **F11.4a** SSE tool events | 6.1 `on_tool_start` / `on_tool_end` / `on_tool_error` | 45 | 0 | REQ-7 / SCN-1 | — |
| | 6.2 dual-channel `aevents()` | 15 | 0 | REQ-7 | — |
| | 6.3 SSE handler tests | 0 | 120 | REQ-7, REQ-9 | `tests/api/test_sse_tool_events.py` (NEW) |
| | **slice total** | **60** | **120** | | **≈180 changed** |
| **F11.4b** chat route swap | 7.1 wire tools + callbacks in route | 40 | 0 | REQ-4, REQ-5 | — |
| | 7.2 swap `model.astream` → `run_agent` | 50 | 0 | REQ-4, REQ-6 / SCN-1, SCN-2, SCN-3 | — |
| | 7.3 chat integration tests | 0 | 150 | REQ-4, REQ-6, REQ-7, REQ-9 / SCN-1, SCN-2, SCN-3 | `tests/api/test_chat.py` (MODIFIED) |
| | 7.4 frontend parity check | 0 | 0 | REQ-10 | `npm run build` |
| | **slice total** | **90** | **150** | | **≈240 changed** |
| **GRAND TOTAL** | 23 tasks | **605** | **800** | 10/10 REQ, 8/8 SCN | **≈1405 changed lines** |

Budget verdict: grand total **≈1405** changed lines, under the 1500 aggregate ceiling. Largest slice = F11.3a at **≈340**, under the 400 individual budget and the 800 orchestrator review budget. Largest single task = 4.3 `run_agent` at **≈90** prod LoC.

---

## 2. Chained-PR decision

- **Chained PRs required: YES** — mandated by `delivery_strategy: auto-chain` and `proposal.md §12` / `design.md §12`.
- **chain_strategy: `stacked-to-main` — RESOLVED** (cached at preflight; do not re-ask, do not mix strategies).
- **decision_needed_before_apply: NO** — all 10 ambiguities resolved, ADR-010 accepted, chain strategy cached.
- Mandatory sub-splits applied per `design.md §17`: F11.3 (≈500 LoC, over budget) → **F11.3a + F11.3b**; F11.4 (≈400 LoC, at boundary) → **F11.4a + F11.4b**.

### Slice sequencing and seams

```
origin/development (d139c9e)
        │
        ├─ F11.0  docs-only ─────────────── seam: zero code; artifacts only, safe to land alone
        │
        ├─ F11.1  deps + stubs ─────────── seam: stub bodies are `pass`/`NotImplementedError`; guarded
        │                                        third-party imports; pytest collects with no ImportError
        │
        ├─ F11.2  MCP client ───────────── seam: only `context7_mcp.py` becomes real; no caller yet
        │                                        (`agent.py` still a stub, `chat.py` untouched)
        │
        ├─ F11.3a agent factory ────────── seam: agent tested against mock model + mock tools;
        │                                        callbacks list accepted but Langfuse still absent
        │
        ├─ F11.3b Langfuse ─────────────── seam: tracer is an optional callback; `None` return keeps
        │                                        F11.3a behavior byte-identical
        │
        ├─ F11.4a SSE tool events ──────── seam: new handler methods are additive; no producer emits
        │                                        tool events yet, so F08 SSE output is unchanged
        │
        └─ F11.4b chat route swap ──────── seam: last slice; composes all prior units. Only slice that
                                                 changes user-visible /api/chat behavior.
                                          → next change: F12 (remaining 5 MCPs, ADR-007)
```

Diff-cleanliness gate before every PR: `git diff <previous-slice-tip> --stat` must show only that slice's rows from §3. A polluted diff is a base bug — rebase/retarget, never squash-merge over it.

---

## 3. Slice plan

### F11.0 — docs-only

| Field | Value |
|---|---|
| Branch | `feature/F11-slice-0` |
| Base | `origin/development` (`d139c9e`) |
| NEW | — |
| MODIFIED | `C:\Users\danie\Downloads\arch-agent\README.md` (env var section) |
| Already in tree | `C:\Users\danie\Downloads\arch-agent\docs\adr\010-context7-agent-runtime.md` (`3526122`) |
| LoC budget | 0 prod / 0 test (docs excluded) |
| REQ/SCN | none (documentation support for REQ-1, REQ-5) |
| Verification | `Select-String -Path README.md -Pattern "CONTEXT7_API_KEY","LANGFUSE_PUBLIC_KEY"` returns hits; `Select-String -Path .env.example -Pattern "CONTEXT7_API_KEY"` already returns line 98 |
| Rollback | revert the README commit; zero runtime impact |

### F11.1 — deps + stubs

| Field | Value |
|---|---|
| Branch | `feature/F11-slice-1` |
| Base | `feature/F11-slice-0` tip (or `origin/development` if F11.0 lands first) |
| NEW | `app\core\context7_mcp.py`, `app\core\agent.py`, `app\core\langfuse_tracer.py`, `tests\core\test_context7_mcp.py`, `tests\core\test_agent.py`, `tests\core\test_langfuse_tracer.py` |
| MODIFIED | `requirements.txt` |
| LoC budget | 120 prod / 90 test (≈210) |
| REQ/SCN | REQ-1, REQ-9 (signatures only for REQ-2/3/5) |
| Verification | `pip install -r requirements.txt`; `pytest tests/core/test_context7_mcp.py tests/core/test_agent.py tests/core/test_langfuse_tracer.py -q`; `pytest -q` (no new failures beyond the 6 known from #66) |
| Rollback | delete the 3 `app/core/` modules + 3 test files, revert 4 `requirements.txt` lines; nothing imports them yet |

### F11.2 — MCP client

| Field | Value |
|---|---|
| Branch | `feature/F11-slice-2` |
| Base | `feature/F11-slice-1` tip |
| NEW | `tests\fixtures\context7_tools.py` |
| MODIFIED | `app\core\context7_mcp.py`, `tests\core\test_context7_mcp.py` |
| LoC budget | 85 prod / 210 test (≈295) |
| REQ/SCN | REQ-2, REQ-6, REQ-9 / SCN-4, SCN-5, SCN-8 |
| Verification | `pytest tests/core/test_context7_mcp.py -q`; live probe `$env:CONTEXT7_API_KEY="<key>"; pytest tests/core/test_context7_mcp.py -q -k live` |
| Rollback | revert `context7_mcp.py` to its F11.1 stub and delete the fixture; `agent.py`/`chat.py` unaffected |

### F11.3a — agent factory

| Field | Value |
|---|---|
| Branch | `feature/F11-slice-3a` |
| Base | `feature/F11-slice-2` tip |
| NEW | — |
| MODIFIED | `app\core\agent.py`, `tests\core\test_agent.py` |
| LoC budget | 180 prod / 160 test (≈340) |
| REQ/SCN | REQ-3, REQ-4 (stream shape), REQ-6, REQ-8 / SCN-1 (partial), SCN-2, SCN-3 |
| Verification | `pytest tests/core/test_agent.py -q`; `pytest tests/core -q` |
| Rollback | revert `agent.py` to its F11.1 stub; `context7_mcp.py` still standalone-tested, `chat.py` untouched |

### F11.3b — Langfuse tracer

| Field | Value |
|---|---|
| Branch | `feature/F11-slice-3b` |
| Base | `feature/F11-slice-3a` tip |
| NEW | — |
| MODIFIED | `app\core\langfuse_tracer.py`, `app\core\agent.py` (trace-name metadata only), `tests\core\test_langfuse_tracer.py` |
| LoC budget | 70 prod / 70 test (≈140) |
| REQ/SCN | REQ-5, REQ-9 / SCN-6, SCN-7 |
| Verification | `pytest tests/core/test_langfuse_tracer.py -q`; env-unset regression `pytest tests/core -q` with `LANGFUSE_*` unset |
| Rollback | revert `langfuse_tracer.py` to stub + drop the metadata lines in `agent.py`; agent keeps working with `callbacks=[SSE]` |

### F11.4a — SSE tool events

| Field | Value |
|---|---|
| Branch | `feature/F11-slice-4a` |
| Base | `feature/F11-slice-3b` tip |
| NEW | `tests\api\test_sse_tool_events.py` |
| MODIFIED | `app\api\sse.py` |
| LoC budget | 60 prod / 120 test (≈180) |
| REQ/SCN | REQ-7, REQ-9 / SCN-1 |
| Verification | `pytest tests/api/test_sse_tool_events.py -q`; `pytest tests/api/test_chat.py -q` (F08 parity, must stay green); `Select-String -Path app\api\sse.py -Pattern "tool_start","tool_end"` |
| Rollback | revert `sse.py` and delete the new test file; no producer emits tool events yet, so F08 SSE bytes are unchanged either way |

### F11.4b — chat route swap

| Field | Value |
|---|---|
| Branch | `feature/F11-slice-4b` |
| Base | `feature/F11-slice-4a` tip |
| NEW | — |
| MODIFIED | `app\api\chat.py`, `tests\api\test_chat.py` |
| LoC budget | 90 prod / 150 test (≈240) |
| REQ/SCN | REQ-4, REQ-6, REQ-7, REQ-9, REQ-10 / SCN-1, SCN-2, SCN-3 |
| Verification | `pytest tests/api/test_chat.py -q`; `pytest -q`; `Select-String -Path app\api\chat.py -Pattern "text/event-stream","X-Accel-Buffering","no-cache"`; `npm run build`; manual smoke — `docker compose up -d --build backend` then POST `/api/chat` with `"como configuro retries en requests?"` and observe `sources` → `tool_start` → `tool_end` → `token`×N → `done` |
| Rollback | revert `chat.py` to the `model.astream(prompt)` path; all other slices remain inert and harmless |

---

## 4. Tasks

### 1. F11.0 — Documentation (docs)

- [ ] **1.1 — Document `CONTEXT7_API_KEY` and `LANGFUSE_*` in README**
  - Slice: F11.0 · Files: MODIFIED `C:\Users\danie\Downloads\arch-agent\README.md`
  - LoC: 0 prod (≈25 doc lines, excluded)
  - REQ/SCN: support for REQ-1, REQ-5
  - Acceptance: `Select-String -Path README.md -Pattern "CONTEXT7_API_KEY"` returns ≥1 hit and states the free-tier-without-key default
  - Commit hint: `docs(f11): document Context7 and Langfuse env vars`

- [ ] **1.2 — Sync F11 openspec artifacts into the slice-0 commit**
  - Slice: F11.0 · Files: `openspec\changes\F11-context7-mcp\{explore,proposal,design,tasks}.md`, `openspec\specs\context7-mcp-integration\spec.md`
  - LoC: 0 (excluded from budget)
  - Acceptance: `git status --short openspec` clean after commit; ADR-010 already present at `docs\adr\010-context7-agent-runtime.md`
  - Commit hint: `docs(f11): add SDD artifacts for Context7 MCP integration`

### 2. F11.1 — Dependencies and module stubs (backend/core)

- [x] **2.1 — Pin the four new dependencies**
  - Slice: F11.1 · Files: MODIFIED `C:\Users\danie\Downloads\arch-agent\requirements.txt`
  - LoC: 4 · REQ-1
  - Content: `langchain-mcp-adapters==0.3.2`, `mcp>=1.0`, `langfuse>=2.0.0`, `langchain>=0.3,<0.4`
  - Acceptance: `pip install -r requirements.txt` exits 0 and `pip show langchain-mcp-adapters` reports `0.3.2`
  - Commit hint: `build(f11): pin Context7 MCP adapter, mcp, langfuse and langchain`

- [x] **2.2 — Create `context7_mcp.py` stub with pinned signatures**
  - Slice: F11.1 · Files: NEW `C:\Users\danie\Downloads\arch-agent\app\core\context7_mcp.py`
  - LoC: ≈30 (±15%) · REQ-2
  - Content: module constants `_BASE_URL`, `_TIMEOUT_SECONDS = 5.0`, `_CLIENT = None`, `_LOGGER`; `build_context7_client()` and `async get_context7_tools()` raising `NotImplementedError`; third-party import guarded inside a `try/except ImportError` so collection never breaks
  - Acceptance: `python -c "import app.core.context7_mcp"` exits 0 with `langchain_mcp_adapters` absent
  - Commit hint: `feat(f11): add Context7 MCP client module skeleton`

- [x] **2.3 — Create `agent.py` stub with pinned signatures**
  - Slice: F11.1 · Files: NEW `C:\Users\danie\Downloads\arch-agent\app\core\agent.py`
  - LoC: ≈55 (±15%) · REQ-3
  - Content: `build_agent(model, system_prompt, tools=None)`, `format_rag_context(rag_documents)`, `async run_agent(model, message, *, callbacks, rag_documents=None)` — all `NotImplementedError`; `ARCHITECT_PERSONA` / `LIBRARY_HINT` prompt constants declared; `create_agent` import guarded
  - Acceptance: `python -c "import app.core.agent"` exits 0
  - Commit hint: `feat(f11): add agent runtime module skeleton`

- [x] **2.4 — Create `langfuse_tracer.py` stub with pinned signatures**
  - Slice: F11.1 · Files: NEW `C:\Users\danie\Downloads\arch-agent\app\core\langfuse_tracer.py`
  - LoC: ≈25 (±15%) · REQ-5
  - Content: `get_langfuse_handler()`, `_env_present()`, `_LOGGER`; `from langfuse.langchain import CallbackHandler` guarded so `CallbackHandler = None` when the package is absent
  - Acceptance: `python -c "import app.core.langfuse_tracer"` exits 0
  - Commit hint: `feat(f11): add Langfuse tracer module skeleton`

- [x] **2.5 — Add import-smoke tests for the three new modules**
  - Slice: F11.1 · Files: NEW `tests\core\test_context7_mcp.py`, `tests\core\test_agent.py`, `tests\core\test_langfuse_tracer.py`
  - LoC: 6 prod / ≈90 test (±15%) · REQ-9
  - Content: per module assert import succeeds, the public callables exist, and the pinned constants (`_BASE_URL == "https://mcp.context7.com/mcp"`, `_TIMEOUT_SECONDS == 5.0`) hold
  - Acceptance: `pytest tests/core/test_context7_mcp.py tests/core/test_agent.py tests/core/test_langfuse_tracer.py -q` all pass; `pytest -q` shows no NEW failures
  - Commit hint: `test(f11): add import smoke tests for the new core modules`

### 3. F11.2 — Context7 MCP client (backend/core)

- [x] **3.1 — Implement `build_context7_client()` with runtime auth header**
  - Slice: F11.2 · Files: MODIFIED `C:\Users\danie\Downloads\arch-agent\app\core\context7_mcp.py`
  - LoC: ≈45 (±15%) · REQ-2 / SCN-4, SCN-5
  - Content: build `Context7ServerConfig` (`transport="http"`, `url=_BASE_URL`, `headers`); read `CONTEXT7_API_KEY` at CALL time (not import time) and `.strip()`; non-empty → `{"Authorization": f"Bearer {key}"}`, else `{}`; memoize into `_CLIENT`
  - Acceptance: `pytest tests/core/test_context7_mcp.py -q -k "headers or singleton"` passes
  - Commit hint: `feat(f11): build Context7 MCP client with runtime bearer auth`

- [x] **3.2 — Implement `get_context7_tools()` with a 5s timeout boundary**
  - Slice: F11.2 · Files: MODIFIED `C:\Users\danie\Downloads\arch-agent\app\core\context7_mcp.py`
  - LoC: ≈40 (±15%) · REQ-2, REQ-6
  - Content: `asyncio.wait_for(client.get_tools(), timeout=_TIMEOUT_SECONDS)`; on `TimeoutError` / `ConnectionError` / HTTP 4xx-5xx raise a typed `Context7Unavailable(reason=...)` carrying `context7_timeout` | `context7_unavailable` | `context7_rate_limited`; WARNING log on every failure path
  - Acceptance: `pytest tests/core/test_context7_mcp.py -q -k "timeout or unavailable"` passes
  - Commit hint: `feat(f11): fetch Context7 tools with a 5s timeout and typed failures`

- [x] **3.3 — Record the tool-name pin fixture**
  - Slice: F11.2 · Files: NEW `C:\Users\danie\Downloads\arch-agent\tests\fixtures\context7_tools.py`
  - LoC: 0 prod / ≈30 test · SCN-8
  - Content: offline recorded tool list exposing exactly `resolve-library-id` and `query-docs`
  - Acceptance: `pytest tests/core/test_context7_mcp.py -q -k tool_names_pinned` passes and fails if either name is renamed
  - Commit hint: `test(f11): pin Context7 tool names with a recorded fixture`

- [x] **3.4 — Unit + live-gated tests for the client**
  - Slice: F11.2 · Files: MODIFIED `C:\Users\danie\Downloads\arch-agent\tests\core\test_context7_mcp.py`
  - LoC: 0 prod / ≈180 test (±15%) · REQ-2, REQ-6, REQ-9 / SCN-4, SCN-5, SCN-8
  - Content: `monkeypatch.setenv` → bearer header; `monkeypatch.delenv` → `{}`; singleton identity across two calls; `asyncio.TimeoutError` side-effect → `Context7Unavailable(reason="context7_timeout")`; `@pytest.mark.skipif(not os.getenv("CONTEXT7_API_KEY"))` live test against the real endpoint
  - Acceptance: `pytest tests/core/test_context7_mcp.py -q` passes with the key unset (live test SKIPPED)
  - Commit hint: `test(f11): cover Context7 client auth, singleton and timeout paths`

### 4. F11.3a — Agent factory (backend/core)

- [x] **4.1 — Implement `format_rag_context()`**
  - Slice: F11.3a · Files: MODIFIED `C:\Users\danie\Downloads\arch-agent\app\core\agent.py`
  - LoC: ≈45 (±15%) · REQ-3, REQ-8
  - Content: numbered prompt block from `list[Document]`, `k≤5` cap, `"(sin contexto RAG)"` for the empty list; flag when any doc has `metadata["source_type"] == "architect_pattern"` so `run_agent` can drop tools per REQ-8
  - Acceptance: `pytest tests/core/test_agent.py -q -k format_rag_context` passes
  - Commit hint: `feat(f11): format RAG documents into the agent system prompt`

- [x] **4.2 — Implement `build_agent()`**
  - Slice: F11.3a · Files: MODIFIED `C:\Users\danie\Downloads\arch-agent\app\core\agent.py`
  - LoC: ≈45 (±15%) · REQ-3
  - Content: `create_agent(model, tools or [], system_prompt=...)`; compose `ARCHITECT_PERSONA` + RAG block + `LIBRARY_HINT`; must accept an empty tools list (RAG-only mode)
  - Acceptance: `pytest tests/core/test_agent.py -q -k build_agent` passes for both empty and populated tool lists
  - Commit hint: `feat(f11): build the LangChain agent with Context7 tools and RAG prompt`

- [x] **4.3 — Implement `run_agent()` streaming with the degraded path**
  - Slice: F11.3a · Files: MODIFIED `C:\Users\danie\Downloads\arch-agent\app\core\agent.py`
  - LoC: ≈90 (±15%) · REQ-4, REQ-6, REQ-8 / SCN-1 (partial), SCN-2, SCN-3
  - Content: `await get_context7_tools()` guarded by try/except `Context7Unavailable` → yield exactly one `{"event": "degraded", "data": {...,"fallback":"rag_only"}}` then continue with `tools=[]`; skip Context7 entirely when the architect-pattern flag is set (REQ-8); drive `agent.astream_events({"messages": [...]}, version="v2")`; truncate any tool result over 4000 chars with the ADR-010 marker
  - Acceptance: `pytest tests/core/test_agent.py -q -k "run_agent or degraded"` passes; degraded event is emitted at most once and before the first token
  - Commit hint: `feat(f11): stream agent events with RAG-only degradation on Context7 failure`

- [x] **4.4 — Agent unit tests**
  - Slice: F11.3a · Files: MODIFIED `C:\Users\danie\Downloads\arch-agent\tests\core\test_agent.py`
  - LoC: 0 prod / ≈160 test (±15%) · REQ-3, REQ-8, REQ-9 / SCN-1 (partial), SCN-2
  - Content: mock `BaseChatModel` + empty tools → tokens only, zero tool events (SCN-2); one synthetic `BaseTool` → exactly one `tool_start` + one `tool_end`; architect-pattern doc → `get_context7_tools` never awaited (REQ-8); `Context7Unavailable` → one `degraded` event then tokens (SCN-3)
  - Acceptance: `pytest tests/core/test_agent.py -q` fully green; `pytest tests/core -q` green
  - Commit hint: `test(f11): cover agent RAG-only, tool and degraded paths`

### 5. F11.3b — Langfuse tracer (backend/core)

- [ ] **5.1 — Implement `get_langfuse_handler()` and `_env_present()`**
  - Slice: F11.3b · Files: MODIFIED `C:\Users\danie\Downloads\arch-agent\app\core\langfuse_tracer.py`
  - LoC: ≈50 (±15%) · REQ-5 / SCN-6
  - Content: both `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` non-empty after `.strip()` → `CallbackHandler()`; otherwise `logger.warning("Langfuse env vars missing; agent will run without tracing.")` and return `None`; swallow SDK construction errors into the same `None` + WARNING path
  - Acceptance: `pytest tests/core/test_langfuse_tracer.py -q` passes
  - Commit hint: `feat(f11): return an optional Langfuse callback handler from env`

- [ ] **5.2 — Attach trace metadata inside `run_agent`**
  - Slice: F11.3b · Files: MODIFIED `C:\Users\danie\Downloads\arch-agent\app\core\agent.py`
  - LoC: ≈20 (±15%) · REQ-5 / SCN-7
  - Content: pass `callbacks` straight through to `astream_events`; include `user_id`, `project_id` (literal `"none"` when null) and model name in the run config metadata / trace name
  - Acceptance: `pytest tests/core/test_agent.py -q -k "callbacks or metadata"` passes; `None` handler leaves behavior identical to F11.3a
  - Commit hint: `feat(f11): tag agent runs with user, project and model metadata`

- [ ] **5.3 — Tracer unit tests**
  - Slice: F11.3b · Files: MODIFIED `C:\Users\danie\Downloads\arch-agent\tests\core\test_langfuse_tracer.py`
  - LoC: 0 prod / ≈70 test (±15%) · REQ-5, REQ-9 / SCN-6
  - Content: `delenv` both keys → `is None` AND the WARNING captured via `caplog` (SCN-6); both set → non-`None` handler (or a patched double when `langfuse` is absent); whitespace-only values treated as unset
  - Acceptance: `pytest tests/core/test_langfuse_tracer.py -q` green
  - Commit hint: `test(f11): assert Langfuse handler env gating and warning`

### 6. F11.4a — SSE tool events (backend/api)

- [ ] **6.1 — Add tool callbacks to `SSEStreamCallbackHandler`**
  - Slice: F11.4a · Files: MODIFIED `C:\Users\danie\Downloads\arch-agent\app\api\sse.py`
  - LoC: ≈45 (±15%) · REQ-7 / SCN-1
  - Content: `on_tool_start` → `{"tool": "<name>"}` and start the latency clock; `on_tool_end` → `{"tool","result_length","latency_ms","status":"ok"}` with `result_length` capped at 4000; `on_tool_error` → the same payload with `status:"error"`, never aborting the stream
  - Acceptance: `pytest tests/api/test_sse_tool_events.py -q` passes; `Select-String -Path app\api\sse.py -Pattern "tool_start","tool_end"` returns hits
  - Commit hint: `feat(f11): emit tool_start and tool_end SSE events from the handler`

- [ ] **6.2 — Add the dual-channel `aevents()` iterator**
  - Slice: F11.4a · Files: MODIFIED `C:\Users\danie\Downloads\arch-agent\app\api\sse.py`
  - LoC: ≈15 (±15%) · REQ-7
  - Content: yield SSE-ready dicts so tool events and tokens never interleave mid-token; guarantee each `tool_end` follows its own `tool_start`
  - Acceptance: `pytest tests/api/test_sse_tool_events.py -q -k order` passes
  - Commit hint: `feat(f11): serialize tool and token events through one SSE queue`

- [ ] **6.3 — SSE handler tests**
  - Slice: F11.4a · Files: NEW `C:\Users\danie\Downloads\arch-agent\tests\api\test_sse_tool_events.py`
  - LoC: 0 prod / ≈120 test (±15%) · REQ-7, REQ-9
  - Content: exact byte assertions `event: tool_start\ndata: {"tool":"resolve-library-id"}\n\n`; `ensure_ascii=False` preserved; pairing order; `status:"error"` on `on_tool_error`; existing `token`/`done` bytes unchanged
  - Acceptance: `pytest tests/api/test_sse_tool_events.py tests/api/test_chat.py -q` all green (F08 parity intact)
  - Commit hint: `test(f11): assert exact SSE bytes for tool events`

### 7. F11.4b — Chat route swap (backend/api)

- [ ] **7.1 — Wire tools, handler and callbacks into the chat route**
  - Slice: F11.4b · Files: MODIFIED `C:\Users\danie\Downloads\arch-agent\app\api\chat.py`
  - LoC: ≈40 (±15%) · REQ-4, REQ-5
  - Content: import `run_agent` and `get_langfuse_handler`; build `callbacks = [SSEStreamCallbackHandler()] + ([lf] if lf else [])`; keep ownership validation, `build_langchain_model(user_id)`, `similarity_search`, and the `event: sources` emission byte-for-byte identical to F08
  - Acceptance: `pytest tests/api/test_chat.py -q -k "sources or auth or ownership"` passes; HTTP 400/401/404/409 paths untouched
  - Commit hint: `feat(f11): wire agent callbacks into the chat route`

- [ ] **7.2 — Swap `model.astream(prompt)` for `run_agent(...)`**
  - Slice: F11.4b · Files: MODIFIED `C:\Users\danie\Downloads\arch-agent\app\api\chat.py`
  - LoC: ≈50 (±15%) · REQ-4, REQ-6 / SCN-1, SCN-2, SCN-3
  - Content: replace the `astream` loop (around `app/api/chat.py:182`) with `async for sse_dict in run_agent(...)`; log a WARNING when the event is `degraded`; keep `Content-Type: text/event-stream`, `Cache-Control: no-cache`, `X-Accel-Buffering: no`; keep the outer try/except `event: error` fallback and guarantee `done` fires
  - Acceptance: `pytest tests/api/test_chat.py -q` green; `Select-String -Path app\api\chat.py -Pattern "X-Accel-Buffering","no-cache","text/event-stream"` returns all three
  - Commit hint: `refactor(f11): stream chat responses through the agent runtime`

- [ ] **7.3 — Chat integration tests for the three scenarios**
  - Slice: F11.4b · Files: MODIFIED `C:\Users\danie\Downloads\arch-agent\tests\api\test_chat.py`
  - LoC: 0 prod / ≈150 test (±15%) · REQ-4, REQ-6, REQ-7, REQ-9 / SCN-1, SCN-2, SCN-3
  - Content: patch `app.core.agent.run_agent` at the module boundary and drive synthetic sequences — SCN-1 two tool pairs then tokens in exact order; SCN-2 zero tool events (assert the `tool_start` substring is absent); SCN-3 `degraded` between `sources` and the first `token`; extend `TestSSEFormat` without deleting existing assertions
  - Acceptance: `pytest tests/api/test_chat.py -q` green; `pytest -q` shows no NEW failures beyond the 6 known from issue #66
  - Commit hint: `test(f11): cover chat SSE tool, RAG-only and degraded flows`

- [ ] **7.4 — Frontend parity and manual smoke**
  - Slice: F11.4b · Files: none (verification only)
  - LoC: 0 · REQ-10
  - Content: confirm zero frontend changes; unknown SSE events ignored by Chainlit
  - Acceptance: `npm run build` exits 0; `git diff --stat origin/development -- frontend` is empty; smoke — `docker compose up -d --build backend`, POST `/api/chat` with `"como configuro retries en requests?"`, observe `sources` → `tool_start` → `tool_end` → `token`×N → `done`; with `mcp.context7.com` blocked, observe `degraded` within ≤5s then RAG-only tokens
  - Commit hint: (no commit — verification evidence recorded in the PR body)

---

## 5. Apply-progress seed

Persisted to Engram as `sdd/F11-context7-mcp/apply-progress` (`type=config`, `capture_prompt=false`):

```json
{
  "started_at": "2026-09-06T00:00:00Z",
  "current_slice": "F11.1",
  "completed_tasks": [],
  "in_flight": "F11.1",
  "blocked": [],
  "notes": "F11.0 is docs-only (no code); F11.1 starts when apply phase begins",
  "apply_progress_handoff_marker": true
}
```

---

## 6. Out of scope

Carried verbatim from `design.md §14`:

- The other 5 MCPs (Filesystem, Puppeteer, Web Search, Fetch, Engram-as-MCP) per ADR-007 — deferred to F12; the `MultiServerMCPClient` dict-of-servers shape keeps them config-only.
- Chainlit frontend changes — unknown SSE events are ignored by the current FE.
- `app/core/llm_model_selector.py` streaming model selector.
- Converting `app/core/engram_client.py` to a real MCP client (ADR-005 defers it).
- `langgraph` / StateGraph adoption.
- The 6 pre-existing backend test failures from issue #66.
- A separate Langfuse ADR — folded into ADR-010.
- SQL migrations — F11 is in-process only.

---

## 7. Risks

Re-stated from `design.md §15` with the task that mitigates each:

1. **Agent runtime regression vs F08 chat behavior** — MED. Mitigated by 7.1 (sources/HTTP paths byte-identical) and 7.3 (SCN-1/SCN-2 parity assertions).
2. **Langfuse env-unset silent skip** — HIGH. Mitigated by 5.1 WARNING log and 5.3 `caplog` assertion (SCN-6).
3. **Context7 tool-name drift (`query-docs` was `get-library-docs`)** — MED. Mitigated by the `==0.3.2` pin in 2.1, the fixture in 3.3, and the live-gated test in 3.4.
4. **Context7 429 / outage** — MED. Mitigated by the 5s timeout in 3.2 and the `degraded` path in 4.3.
5. **Context budget blow on small models (Ollama `llama3`, 8k ctx)** — HIGH. Mitigated by the `k≤5` cap in 4.1 and the 4000-char truncation in 4.3.
6. **`requirements.txt` bump → 5–8 min backend image rebuild** — LOW. Documented in the F11.1 PR body (task 2.1).
7. **`CONTEXT7_API_KEY` leakage** — LOW. Key read from env at call time only (3.1); `.env` already gitignored.
8. **Outbound `mcp.context7.com` blocked in CI/sandbox** — MED. Mitigated by `skipif` gating in 3.4 plus the offline fixture in 3.3.
9. **System-prompt bloat → Context7 called when no library is named** — MED. Mitigated by the `LIBRARY_HINT` prompt in 4.2 and the REQ-8 short-circuit in 4.3.
10. **`create_agent` API churn** — MED. Mitigated by the `langchain>=0.3,<0.4` floor in 2.1.
11. **Dual tool-call latency** — MED. Mitigated by the 4000-char cap in 4.3 and `latency_ms` observability in 6.1.
12. **F11.3 / F11.4 over the 400-line budget** — RESOLVED. Split into F11.3a/F11.3b and F11.4a/F11.4b; largest slice is now ≈340 changed lines.

---

## 8. References

| Artifact | Path | Commit |
|---|---|---|
| Exploration | `openspec/changes/F11-context7-mcp/explore.md` | `3526122` |
| Proposal | `openspec/changes/F11-context7-mcp/proposal.md` | `3526122` |
| Spec delta | `openspec/specs/context7-mcp-integration/spec.md` | `223f7b4` |
| Design | `openspec/changes/F11-context7-mcp/design.md` | `72b1b21` |
| ADR-010 | `docs/adr/010-context7-agent-runtime.md` | `3526122` |
| Swap point | `app/api/chat.py:182` (`model.astream(prompt)`) | `d139c9e` |
| SSE handler | `app/api/sse.py:7` (`SSEStreamCallbackHandler`) | `d139c9e` |
| RAG (unchanged) | `app/core/rag.py:186` (`similarity_search`) | `d139c9e` |
| LLM factory (reused) | `app/core/llm_loader.py:104` (`build_langchain_model`) | `d139c9e` |
| Issue | [#13 — [F11] Context7 MCP integrado](https://github.com/danielCH26/arch-agent/issues/13) | — |
