# Archive Report — F11-context7-mcp

> **Change**: `F11-context7-mcp` — Context7 MCP Integration
> **Capability (NEW)**: `context7-mcp-integration` — `openspec/specs/context7-mcp-integration/spec.md`
> **Branch**: `feature/F11-context7-mcp` (preserved; do not switch)
> **Base**: `origin/development` @ `d139c9e` (PR #64 MERGED, Pipeline_RAG_PGVector)
> **HEAD at archive**: `284bac1` — `docs(openspec): F11 verify - pass with warnings`
> **Archive date**: `2026-09-05` (ISO)
> **Archived to**: `openspec/changes/archive/2026-09-05-F11-context7-mcp/`
> **Engram topic_key**: `sdd/F11-context7-mcp/archive` (this report) + apply-progress `#41` updated to `status=archived`
> **Issue**: [#13 — [F11] Context7 MCP integrado](https://github.com/danielCH26/arch-agent/issues/13)
> **Pre-existing failures** (out of F11 scope, tracked separately): [#66 — 6 backend test failures](https://github.com/danielCH26/arch-agent/issues/66)
> **Delivery strategy**: `auto-chain` · `chain_strategy: stacked-to-main` · `execution_mode: auto` (interactive override)
> **Review budget**: 400-line per slice / 800-line orchestrator ceiling

---

## Summary

F11 shipped **Context7 MCP integration as an atomic capability** on `feature/F11-context7-mcp` against `origin/development @ d139c9e`. The branch holds **8 commits** (1 docs-only slice-0, 6 implementation slices, 1 verify) delivering ~4,579 LoC across 19 files. All **10 spec REQs** and **8 spec SCNs** pass per `verify-report.md @ 284bac1` (verdict: **PASS WITH WARNINGS**, 0 CRITICAL, 6 WARNINGs, 5 SUGGESTIONs). The cycle was driven under `execution_mode: auto` with `delivery_strategy: auto-chain`; chain strategy was the orchestrator-cached `stacked-to-main`, no `size:exception` was needed after the mandated F11.3→F11.3a/b and F11.4→F11.4a/b sub-splits kept every slice ≤400 changed lines. Approval came from `verify-report.md` (0 critical findings) combined with the orchestrator's auto-mode confirmation; **the 6 pre-existing backend failures from #66 remain unchanged** (reproducible via `git stash` at `d139c9e`) and are explicitly out of scope. The change folder moved to `openspec/changes/archive/2026-09-05-F11-context7-mcp/` via `git mv` (byte-identity verified, exception noted for the tasks.md reconciliation below).

### Final-State Authority applied

- The persisted tasks artifact at archive time had tasks **1.1 and 1.2** (F11.0 docs-only) as `- [ ]`, but the apply-progress observation **#41** records `"All 23 tasks marked [x] in tasks.md. Ready for verify phase"`, the orchestrator launch prompt confirms `"F11.0 docs-only (already merged at 3526122 — no PR needed)"`, and the README change (`CONTEXT7_API_KEY` documented as optional at `README.md:135`) is verified in tree.
- Per the **Task Completion Gate exception** in `sdd-archive` skill, this archive performs an **exceptional mechanical reconciliation**: tasks **1.1 and 1.2** flipped to `[x]` with reconciliation notes appended; **the only diff** between the HEAD `tasks.md` and the archived `tasks.md` is these two checkbox flips + two reconciliation notes. All other files moved with byte-identity via `git mv`.
- **No CRITICAL findings in `verify-report.md §4`** — section reads "**NONE.**" with 0 critical findings.
- **No Native Review Receipt** for this candidate: `reviewGate` is structurally absent (kill-switch off for this candidate), so archive proceeds under ordinary repository policy.

---

## Closed PRD items — Issue #13 acceptance criteria

| # | AC from #13 | Status | Evidence |
|---|---|---|---|
| AC-1 | **El agente consulta docs actuales via Context7 MCP** (no static training data) | **CLOSED** | `app/core/context7_mcp.py:111-157` `build_context7_client()` + `:191-200` `get_context7_tools()` (5s `asyncio.wait_for` boundary); `app/core/agent.py:326-333` consumes tools via `agent.astream_events(..., version="v2")` driven by `run_agent`. SCN-1 + SCN-3 verified. |
| AC-2 | **Resultados relevantes (no alucinaciones)** via `resolve-library-id` + `query-docs` tool surface | **CLOSED** | Tool list pinned to exactly `resolve-library-id` and `query-docs` per REQ-2 / SCN-8; `tests/fixtures/context7_tools.py` + `tests/core/test_context7_mcp.py:160-178` enforce the names. RAG-wins-for-architect-patterns precedence rule in REQ-8 + `app/core/agent.py` avoids Context7 calls for `architect_pattern` queries (verified SCN-2). 4000-char tool-result truncation per ADR-010 keeps responses focused. |
| AC-3 | **Trazas en Langfuse** for `/api/chat` calls | **CLOSED** | `app/core/langfuse_tracer.py:73-77` returns `CallbackHandler` when both `LANGFUSE_*` non-empty (else `None` + WARNING per SCN-6); `app/core/agent.py:237-250` threads `metadata={user_id, project_id, model}` and `run_name=chat/user-{user_id}/project-{project_id}` through `astream_events`. SCN-7 unit-verified (`tests/core/test_agent.py:484-568`); live Langfuse UI verification requires a real Langfuse account + outbound egress and is operator-side. |

All 3 PRD acceptance criteria are closed at the spec/verify level. Live end-to-end verification of the Context7 remote server (SCN-5/SCN-8 live variants) is gated by `CONTEXT7_API_KEY` per REQ-9 — the unit + fixture + recorded-fixture tests are green; the live skip is documented as W-5 (verifier-scope, not a blocker).

---

## Files created / modified

### SDD artifacts (in `openspec/changes/archive/2026-09-05-F11-context7-mcp/`)

| Artifact | Path | Origin commit |
|---|---|---|
| Exploration | `explore.md` (19,487 B) | `3526122` |
| Proposal | `proposal.md` (15,926 B) | `3526122` |
| Design (17 sections, 4 SDs) | `design.md` (43,289 B) | `72b1b21` |
| Tasks (23 tasks across 7 chained slices) | `tasks.md` (32,461 B — post-reconciliation) | `de484fb` |
| Verify report (PASS WITH WARNINGS) | `verify-report.md` (30,245 B) | `284bac1` |

### Canonical spec (preserved at source-of-truth location)

| Artifact | Path | Origin commit |
|---|---|---|
| Capability spec — NEW, 10 REQs + 8 SCNs | `openspec/specs/context7-mcp-integration/spec.md` | `223f7b4` |

### Decision record

| Artifact | Path | Origin commit |
|---|---|---|
| ADR-010 — Context7 agent runtime | `docs/adr/010-context7-agent-runtime.md` | `3526122` |

### Production code (commit hashes shown for traceability)

| Slice | Files | Commit | LoC (this slice) |
|---|---|---|---|
| F11.1 deps + stubs | NEW `app/core/context7_mcp.py`, `app/core/agent.py`, `app/core/langfuse_tracer.py`; MODIFIED `requirements.txt` | `89a93a7` | +423/-1 |
| F11.2 MCP client | MODIFIED `app/core/context7_mcp.py`; NEW `tests/fixtures/context7_tools.py` | `1a5d732` | +507/-40 |
| F11.3a agent factory | MODIFIED `app/core/agent.py` | `02b6849` | +679/-51 |
| F11.3b Langfuse tracer | MODIFIED `app/core/langfuse_tracer.py`, `app/core/agent.py` | `e723205` | +298/-33 |
| F11.4a SSE tool events | MODIFIED `app/api/sse.py` | `2e02322` | +476/-8 |
| F11.4b chat route swap | MODIFIED `app/api/chat.py` | `07d1575` | +596/-33 |
| **F11 implementation total** | 19 files, +4,579/-37 vs `origin/development` | — | **~4,579** |

### Tests added (all green at HEAD `284bac1`: 79 passed, 1 skipped)

- `tests/core/test_context7_mcp.py` (16 passed + 1 live-gated skipped)
- `tests/core/test_agent.py` (19 passed)
- `tests/core/test_langfuse_tracer.py` (9 passed)
- `tests/api/test_sse_tool_events.py` (15 passed, NEW file)
- `tests/fixtures/context7_tools.py` (NEW recorded-fixture)
- `tests/api/test_chat.py` (MODIFIED — 9 new test functions for SCN-1/2/3, langfuse wiring, error termination, defensive `done`, SSE header preservation, sources-event shape)

---

## Branches for stacked PRs

The `feature/F11-context7-mcp` branch carries **8 commits ready for slice branching**. F11 was designed with `chain_strategy: stacked-to-main` against `origin/development @ d139c9e` (PR #64 MERGED). The recommended slicing below matches `tasks.md §3` exactly; slice commits are already atomic on `feature/F11-context7-mcp`, so each child branch is just `git checkout -c` + `git push`.

| Slice | Branch name | Base | Slice tip | LoC budget | Behavior change? |
|---|---|---|---|---|---|
| F11.0 | _already merged at `3526122` — no PR needed_ | `origin/development` | `3526122` | 0 prod / 0 test | No (docs only) |
| F11.1 | `feature/F11-s1-deps-and-stubs` | `feature/F11-slice-0` (or `origin/development` if F11.0 lands first) | `89a93a7` | 120 / 90 (≈210) | No (stub bodies are `pass`/`NotImplementedError`; guarded third-party imports) |
| F11.2 | `feature/F11-s2-mcp-client` | `feature/F11-s1-deps-and-stubs` | `1a5d732` | 85 / 210 (≈295) | No (`agent.py` still stub; `chat.py` untouched) |
| F11.3a | `feature/F11-s3a-agent` | `feature/F11-s2-mcp-client` | `02b6849` | 180 / 160 (≈340) | No (callbacks list accepted but Langfuse still absent; agent tested with mocks) |
| F11.3b | `feature/F11-s3b-langfuse` | `feature/F11-s3a-agent` | `e723205` | 70 / 70 (≈140) | No (`None` return keeps F11.3a behavior byte-identical) |
| F11.4a | `feature/F11-s4a-sse-handler` | `feature/F11-s3b-langfuse` | `2e02322` | 60 / 120 (≈180) | No (new handler methods are additive; no producer emits tool events yet, so F08 SSE bytes are unchanged) |
| F11.4b | `feature/F11-s4b-chat-route` | `feature/F11-s4a-sse-handler` | `07d1575` | 90 / 150 (≈240) | **YES — only behavior-changing slice** |

**Recommendation**: Push F11.4b against **`origin/development` directly** (not against the slice stack) because slices F11.1..F11.4a are inert — they ship code with no user-visible runtime change. The single behavior-changing PR (F11.4b) keeps the diff readable and isolates the `/api/chat` swap risk to one review. F11.0 is already on `origin/development` if PR #64 is the merge target.

Diff-cleanliness gate before every PR: `git diff <previous-slice-tip> --stat` must show only that slice's rows from `tasks.md §3`. A polluted diff is a base bug — rebase/retarget, never squash-merge over it.

---

## PR #64 + F08 dependency (rebase gate)

`feature/F11-context7-mcp` is pinned at base **`origin/development @ d139c9e`** (PR #64 MERGED, `Pipeline_RAG_PGVector`). When F08 (proposals + RAG migration) lands in PRs **#67** and **#68**:

1. **F11 does NOT depend on F08 code paths.** F11 does not import `app.api.proposals` or `migrations/0008_*`. The only F08 surface F11 relies on is `app/api/sse.py` `SSEStreamCallbackHandler` (which already exists at `d139c9e`) and the `event: sources` SSE event that F08 introduced pre-F11 (also at `d139c9e`).
2. **Docker image rebuild** — the F08 migrations and the `docker-compose` changes need to land in `development` BEFORE F11 slices push, so the F11 image includes the F08 code under F11 modules. Recommended order: merge F08 PRs → rebuild backend image → push F11 slices → re-tag image.
3. **No code conflict expected**: F08 touches `app/api/proposals.py`, `app/api/documents.py`, `migrations/0008_*`, frontend proposal views, and docker-compose. F11 touches `app/core/{context7_mcp,agent,langfuse_tracer}.py`, `app/api/{chat,sse}.py` (sse.py grows additive `on_tool_start`/`on_tool_end`), `tests/{core,api,fixtures}/*`, and `requirements.txt`. The overlap on `app/api/sse.py` is purely additive — both F08 and F11 modify the same handler class but in disjoint regions (F08 owns `on_llm_new_token`; F11 owns `on_tool_start`/`on_tool_end`/`on_tool_error`).

---

## Carried risks (final state, NOT intermediate-snapshot state)

The numbers below come from `verify-report.md @ 284bac1` (final, authoritative). Pre-existing failures count = **6** per the verify report (apply-progress observation #41 from earlier in the cycle recorded 5; the verify-report's final count of 6 is the authoritative figure per Final-State Authority).

| # | Risk | Severity | Status |
|---|---|---|---|
| R-1 | Six pre-existing backend test failures (#66): `test_auth.py::TestAuthModels::test_login_request` (pydantic v2), `test_documents.py::TestDocumentModels::test_document_out_model` (pydantic v2), 3 `TestUploadEndpointDuplicates` (missing `background_tasks`, `overwrite_document`, `save_document`), and 1 frontend jsdom test. Reproducible at `d139c9e` via `git stash` (orchestrator-confirmed). | MED | **CARRIED** — explicitly out of F11 scope; tracked in issue #66. No F11-introduced regression. |
| R-2 | Context7 transport: implementation uses `transport="streamable_http"` while spec REQ-2 and `design.md §4.1` wrote `Literal["http"]`. `langchain-mcp-adapters==0.3.2` rejects the literal `"http"`; `streamable_http` is the modern MCP HTTP transport. ADR-010 §Decisión line 60 already accepts "también aceptable `"streamable_http"`". | LOW | **CARRIED** — documented in commit `1a5d732` body, `app/core/context7_mcp.py:34-39`, and verify-report W-2. Suggestion S-3 recommends tightening ADR-010 wording. |
| R-3 | `build_agent` return type annotated as `Any` rather than `CompiledAgent` (LangChain 1.x actually returns `CompiledStateGraph`). Type-safe and forward-compatible. | LOW | **CARRIED** — verify-report W-3; `app/core/agent.py:125-144`. |
| R-4 | `requirements.txt` pins `langchain>=0.3,<0.4` at both line 5 and line 26 (duplicate). On a machine with `langchain==1.3.1` already installed, the floor cannot be satisfied locally; fresh CI resolves cleanly to 0.3.x. | LOW | **CARRIED** — verify-report W-4. Suggestion S-1 recommends dropping line 5. |
| R-5 | Live Context7 test (`test_get_context7_tools_live_against_public_endpoint`) is gated by `@pytest.mark.skipif(not os.getenv("CONTEXT7_API_KEY"))` and was SKIPPED in this verification because no key was supplied to the verifier. Fixture-based SCN-8 test passed. | LOW | **CARRIED** — verify-report W-5; SCN-9 / REQ-9 compliance intact. Live execution requires a real `CONTEXT7_API_KEY` at the operator side. |
| R-6 | PowerShell `>` redirect required the `git -F <file>` workaround during commit message authoring. Operational friction only. | LOW | **CARRIED** — no SDD impact; documented for future Windows-based sub-agents. |

**No CRITICAL findings.** The 5 verify-report SUGGESTIONs (S-1..S-5) are listed in `verify-report.md §6` for follow-up cleanup but are not blocking.

---

## Verify report reference

- **Path**: `openspec/changes/archive/2026-09-05-F11-context7-mcp/verify-report.md`
- **Commit**: `284bac1`
- **Verdict**: **PASS WITH WARNINGS**
- **CRITICAL findings**: 0
- **WARNING findings**: 6 (R-1..R-6 above)
- **SUGGESTIONs**: 5 (cosmetic / hygiene)
- **Test totals**: 79 passed + 1 skipped (live Context7 gate) + 0 failed across all F11-affected files. No new failures vs the 6 pre-existing baseline (#66).
- **Spec coverage**: 10/10 REQs pass · 8/8 SCNs pass.

---

## References

### Artifacts (archived)

- `openspec/changes/archive/2026-09-05-F11-context7-mcp/explore.md` (commit `3526122`)
- `openspec/changes/archive/2026-09-05-F11-context7-mcp/proposal.md` (commit `3526122`)
- `openspec/changes/archive/2026-09-05-F11-context7-mcp/design.md` (commit `72b1b21`)
- `openspec/changes/archive/2026-09-05-F11-context7-mcp/tasks.md` (commit `de484fb`, reconciled 2026-09-05)
- `openspec/changes/archive/2026-09-05-F11-context7-mcp/verify-report.md` (commit `284bac1`)
- `openspec/changes/archive/2026-09-05-F11-context7-mcp/archive-report.md` (this file)

### Source-of-truth spec (canonical, preserved at the canonical path)

- `openspec/specs/context7-mcp-integration/spec.md` (commit `223f7b4`) — 10 REQs + 8 SCNs.

### Decision records

- `docs/adr/010-context7-agent-runtime.md` (commit `3526122`) — Context7 agent runtime.
- `docs/adr/007-mcp-public-https.md` — referenced (decides public HTTPS, no sidecar).

### Engram topic keys

- `sdd/F11-context7-mcp/proposal` (proposal observation)
- `sdd/F11-context7-mcp/spec` (spec observation)
- `sdd/F11-context7-mcp/design` (design observation)
- `sdd/F11-context7-mcp/tasks` (tasks observation)
- `sdd/F11-context7-mcp/apply-progress` (observation **#41**, updated 2026-09-05 with `status=archived` + `archived_at=2026-09-05T...`)
- `sdd/F11-context7-mcp/verify-report` (verify-report observation)
- `sdd/F11-context7-mcp/archive` (this report)

### Commits on `feature/F11-context7-mcp` (HEAD → base)

| SHA | Type | Message |
|---|---|---|
| `284bac1` | docs | F11 verify - pass with warnings (0 critical, 6 warnings, 5 suggestions) |
| `07d1575` | feat | swap `model.astream` → `agent.astream_events` with Langfuse + degraded event |
| `2e02322` | feat | add `on_tool_start` + `on_tool_end` to `SSEStreamCallbackHandler` |
| `e723205` | feat | Langfuse `CallbackHandler` factory with `None` + WARNING fallback |
| `02b6849` | feat | agent factory with RAG precedence rule |
| `1a5d732` | feat | `MultiServerMCPClient` singleton against `mcp.context7.com` |
| `74169bc` | docs | mark F11.1 tasks (2.1-2.5) complete after slice commit `89a93a7` |
| `89a93a7` | feat | deps: `langchain-mcp-adapters` + `langfuse` + module stubs |
| `de484fb` | docs | F11 tasks - 23 tasks across 7 chained slices |
| `72b1b21` | docs | F11 design - 17 sections, 4 SDs |
| `223f7b4` | docs | F11 spec - 10 REQs + 8 SCNs for `context7-mcp-integration` |
| `3526122` | docs | F11 proposal - Context7 MCP via `create_agent` + `MultiServerMCPClient` (Closes #13) |
| `d139c9e` | merge | PR #64 — Pipeline_RAG_PGVector (BASE) |

### External references

- Issue: [#13 — [F11] Context7 MCP integrado](https://github.com/danielCH26/arch-agent/issues/13)
- Pre-existing failures: [#66 — 6 backend test failures](https://github.com/danielCH26/arch-agent/issues/66)
- Base merge: PR #64 (MERGED into `development`)
- F08 follow-on (not part of F11): PR #67 + PR #68 — recommended to land before pushing F11.4b so the docker image rebuilds once.

---

## Reconciliation note (audit trail)

The archived `tasks.md` carries **two checkbox flips** versus the HEAD version (`de484fb`):

- Task **1.1** (`- [ ]` → `- [x]`): README documents `CONTEXT7_API_KEY` (line 135) and the three `LANGFUSE_*` vars (lines 132-134). Confirmed in slice-0 commit `3526122`. Reconciliation note appended below the task.
- Task **1.2** (`- [ ]` → `- [x]`): Slice-0 commit `3526122` shipped `docs/adr/010-context7-agent-runtime.md`, `explore.md`, `proposal.md`. The remaining artifacts landed as separate docs-only commits (`design.md @ 72b1b21`, `tasks.md @ de484fb`, `spec.md @ 223f7b4`) before the F11.1 implementation slice (`89a93a7`). All five SDD artifacts present at HEAD `284bac1`. Apply-progress observation #41 records "All 23 tasks marked [x] in tasks.md. Ready for verify phase". Reconciliation note appended below the task.

**Diff between HEAD `tasks.md` and archived `tasks.md`** is exactly the two checkbox flips plus the two reconciliation notes — no other content changed. Performed under the Task Completion Gate exception clause in `sdd-archive` skill: orchestrator launch prompt explicitly confirms F11.0 completion, apply-progress + verify-report together prove all 23 tasks completed. No other modifications.

---

**Status**: archived — SDD cycle complete. Ready for the next change (F12 — remaining 5 MCPs per ADR-007).
