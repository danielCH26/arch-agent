# Context7 MCP Integration — Specification

Capability folder: `openspec/specs/context7-mcp-integration/`. Branch: `feature/F11-context7-mcp` @ `d139c9e`. Proposal: `openspec/changes/F11-context7-mcp/proposal.md`. Engram topic_key: `sdd/F11-context7-mcp/spec`. Issue: [#13](https://github.com/danielCH26/arch-agent/issues/13).

## Purpose

Introduce a LangChain `create_agent` runtime in `app/` that calls the Context7 MCP server over HTTPS, surfaces tool events over SSE, and emits Langfuse traces. One atomic spec consolidates the 3 proposal §8 capabilities (`context7-mcp-integration`, `agent-runtime`, `langfuse-tracing`) because F11 is atomic.

## Requirements

| ID | Requirement |
|---|---|
| REQ-1 | `requirements.txt` MUST add `langchain-mcp-adapters==0.3.2`, `mcp>=1.0`, `langfuse>=2.0.0`, `langchain>=0.3,<0.4`. |
| REQ-2 | `app/core/context7_mcp.py` MUST expose async `get_context7_tools()` → singleton `MultiServerMCPClient` (`transport="http"`, `url="https://mcp.context7.com/mcp"`). When `CONTEXT7_API_KEY` non-empty, `headers={"Authorization": f"Bearer {key}"}`; else `{}`. Tool list MUST be exactly `resolve-library-id`, `query-docs` (fixture asserts both). |
| REQ-3 | `app/core/agent.py` MUST expose `build_agent(model, system_prompt)` via `langchain.agents.create_agent(model, tools, system_prompt=...)` with Context7 tools + RAG prompt-injection. |
| REQ-4 | `app/api/chat.py` MUST replace `model.astream(prompt)` with `agent.astream_events({"messages": [...]}, version="v2")`. RAG `event: sources` MUST be emitted before tokens with F08 JSON shape. |
| REQ-5 | `app/core/langfuse_tracer.py` MUST return `langfuse.langchain.CallbackHandler` when `LANGFUSE_PUBLIC_KEY` AND `LANGFUSE_SECRET_KEY` non-empty; else `None` + WARNING. When non-None, `astream_events` MUST receive `callbacks=[..., handler]`; trace name MUST include `project_id` (`"none"` when null). |
| REQ-6 | Context7 HTTP MUST timeout at 5s. On timeout/conn-error/HTTP 4xx-5xx, SSE MUST yield `event: degraded\ndata: {"source":"context7","reason":"context7_unavailable"}\n\n` then continue with RAG-only tokens. |
| REQ-7 | `SSEStreamCallbackHandler` MUST emit `event: tool_start\ndata: {"tool":"<name>"}\n\n` and `event: tool_end\ndata: {"tool":"<name>","result_length":<int>}\n\n`. |
| REQ-8 | When RAG returns ≥1 doc with `metadata["source_type"]=="architect_pattern"`, agent MUST NOT call Context7. RAG runs unconditionally; Context7 additive only for non-pattern queries. |
| REQ-9 | Pytest MUST cover each REQ in `tests/core/test_context7_mcp.py`, `test_agent.py`, `test_langfuse_tracer.py`, `tests/api/test_chat.py`. Live Context7 tests MUST skip via `@pytest.mark.skipif(not os.getenv("CONTEXT7_API_KEY"))`. |
| REQ-10 | `npm run build` MUST continue to succeed; F11 has zero frontend changes; unknown SSE events MUST be ignored by Chainlit. |

## Scenarios

| ID | GIVEN / WHEN / THEN |
|---|---|
| SCN-1 | Configured LLM + `"como configuro retries en requests?"` WHEN POST /api/chat THEN SSE = `sources` → `tool_start(resolve-library-id)` → `tool_end` → `tool_start(query-docs)` → `tool_end` → `token`×N → `done`. |
| SCN-2 | `"explica el patron saga"` + RAG returns ≥1 `source_type="architect_pattern"` WHEN POST /api/chat THEN SSE = `sources` → `token`×N → `done` (NO tool events). |
| SCN-3 | `mcp.context7.com` unreachable WHEN POST /api/chat THEN within ≤5s `event: degraded` (`reason=context7_unavailable`), then RAG-only `token`×N → `done`. |
| SCN-4 | `CONTEXT7_API_KEY="ctx7_test_key"` WHEN client built THEN `headers == {"Authorization": "Bearer ctx7_test_key"}`. |
| SCN-5 | `CONTEXT7_API_KEY=""` WHEN client built THEN `headers == {}` AND request succeeds. |
| SCN-6 | Both `LANGFUSE_*` empty WHEN `get_langfuse_handler()` called THEN returns `None` + WARNING; agent runs untraced. |
| SCN-7 | Both `LANGFUSE_*` non-empty WHEN /api/chat completes with `project_id=42` THEN Langfuse UI shows trace with `user_id`, `project_id="42"`, model, tool names, latency. |
| SCN-8 | `tests/fixtures/context7_tools.py` recorded output WHEN `test_tool_names_pinned` runs THEN fails if `resolve-library-id` or `query-docs` missing/renamed. |

## Data Model & Out of Scope

NEW: `app/core/{context7_mcp,agent,langfuse_tracer}.py`, `tests/fixtures/context7_tools.py`. MODIFIED: `app/api/{chat,sse}.py`, `requirements.txt`. Env: `CONTEXT7_API_KEY`, `LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY` (optional). No SQL migrations. Out of scope: other 5 MCPs (ADR-007); Chainlit UI; `engram_client.py` MCP-conversion; `langgraph`; 6 pre-existing backend test failures (#66); streaming model selector.

## Risks

`create_agent` API churn → `langchain>=0.3,<0.4` (REQ-1). Context7 rename → pin + fixture (REQ-2, SCN-8). Langfuse silent skip → None + WARNING (REQ-5, SCN-6). Context budget blow → RAG `k≤5`, Context7 4000-char cap. Egress blocked CI → `skipif` (REQ-9). Chat regressions vs F08 → parity SCN-1/2.

## References

`openspec/changes/F11-context7-mcp/{proposal,explore}.md`; `docs/adr/{010,001,004,005,007}`; issue #13. Folder `context7-mcp-integration` consolidates 3 proposal §8 capabilities; cross-cutting for future split: `agent-runtime`, `langfuse-tracing`.
