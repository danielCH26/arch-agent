# Puppeteer MCP Integration — Specification

**Capability folder:** `openspec/specs/puppeteer-mcp-integration/`
**Branch:** `feature/F13-puppeteer-mcp` @ `4c5a9d3`
**Issue:** [#17](https://github.com/danielCH26/arch-agent/issues/17) — [F13] Puppeteer MCP integrado

## Scope Confirmation

**F13 ships Mermaid-only rendering. Arbitrary HTML rendering (including any sanitizer) is OUT of scope for F13; revisit as F14.** The agent invokes `puppeteer_screenshot` exclusively on a fenced `mermaid` block it just emitted.

## Purpose

Render fenced Mermaid code blocks emitted by the agent as inline PNG images through a `streamable_http` Puppeteer MCP sidecar. Tool surface is restricted, per-call budgets are bounded, render failures fall back to text. ADR-013 records the sidecar + transport choice and the security posture.

## Requirements

| ID | Requirement |
|---|---|
| REQ-PMCP-1 | When the agent emits a fenced `mermaid` block, `_persist_turn` SHALL save the PNG under `/app/uploads/screenshots/<id>.png` AND the SSE handler SHALL emit `event: attachment` with `{kind, mime, url, filename}` BEFORE `event: done`. |
| REQ-PMCP-2 | `get_puppeteer_tools()` SHALL expose a positive allow-list containing exactly `puppeteer_screenshot` AND a hardened `puppeteer_evaluate` restricted to `data:` URLs; `puppeteer_navigate` / `puppeteer_click` / `puppeteer_fill` / `puppeteer_select` / `puppeteer_hover` SHALL be filtered out. |
| REQ-PMCP-3 | Per-call budget SHALL be `asyncio.wait_for(timeout=15s)` AND a 2 MB byte cap on the PNG response. |
| REQ-PMCP-4 | Per-user render rate limit SHALL be 5 renders / 60 s; the 6th request SHALL emit `event: degraded` with `reason="puppeteer_rate_limited"` AND the agent SHALL fall back to a textual diagram description. |
| REQ-PMCP-5 | Render tool calls SHALL flow through the existing `CallbackHandler` wiring so a Langfuse span appears automatically when `LANGFUSE_PUBLIC_KEY` AND `LANGFUSE_SECRET_KEY` are set (no new tracer code). |

## Scenarios

| ID | GIVEN / WHEN / THEN |
|---|---|
| SCN-PMCP-1 | Agent emits a Mermaid block; SSE stream completes. THEN `_persist_turn` writes `/app/uploads/screenshots/<uuid>.png` AND SSE emits `event: attachment` carrying `{kind:"screenshot", mime:"image/png", url:"/api/chat/attachments/<id>?token=…", filename:"diagram-<ts>.png"}` BEFORE `event: done`. |
| SCN-PMCP-2 | Agent emits NO Mermaid block; SSE stream completes. THEN zero `event: attachment` events appear. |
| SCN-PMCP-3 | Puppeteer MCP server returns the full default tool set. THEN `get_puppeteer_tools()` returns exactly `puppeteer_screenshot` AND hardened `puppeteer_evaluate`; `puppeteer_navigate` is absent. |
| SCN-PMCP-4 | Render does not complete within 15 s. THEN `PuppeteerUnavailable(reason="puppeteer_timeout")` is raised AND SSE emits `event: error` with `data: "messages store unavailable"` (mirrors F12 SCN-7). |
| SCN-PMCP-5 | Render returns a PNG larger than 2 MB. THEN the route rejects the response AND SSE emits `event: error`. |
| SCN-PMCP-6 | User at 5 renders / 60 s; a 6th is requested. THEN SSE emits `event: degraded` with `reason="puppeteer_rate_limited"` AND the agent produces a textual diagram description. |
| SCN-PMCP-7 | Render completes AND `LANGFUSE_PUBLIC_KEY` + `LANGFUSE_SECRET_KEY` are set. THEN a Langfuse span for the tool call appears in the trace tree without explicit instrumentation. |

## Out of Scope

- Arbitrary HTML rendering (sanitizer + `puppeteer_navigate` allow-list): F14.
- Multi-turn memory-driven rendering decisions: F14 (requires `run_agent` to read conversation history).
- `puppeteer_pdf` and the community `merill-git/mcp-server-puppeteer` fork: not adopted.
- Horizontal scaling of the sidecar / a render queue.

## Risks

- Tool surface leakage → REQ-PMCP-2 positive allow-list + recorded fixture test.
- Hung Chromium → REQ-PMCP-3 timeout + `mem_limit: 512m` on the sidecar.
- Render abuse → REQ-PMCP-4 rate limit + REQ-PMCP-3 byte cap.
- Cross-turn scope drift → see "Out of Scope".

## References

- `openspec/changes/2026-09-07-F13-puppeteer-mcp/{explore,proposal}.md`
- `app/core/context7_mcp.py` — F11 `MultiServerMCPClient` pattern mirrored.
- `app/core/langfuse_tracer.py` — F11 wiring REQ-PMCP-5 depends on.
- `docs/adr/007-six-mcps.md:78` — names the Puppeteer package.
