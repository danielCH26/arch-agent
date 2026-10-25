# Proposal: F08 — Propuesta + Aprobación

| Field | Value |
|---|---|
| Slug | `F08-propuesta-aprobacion` |
| Issue | [#12 — [F08] Generación propuesta + aprobación](https://github.com/danielCH26/arch-agent/issues/12) (labels: feature, sprint-2, backend) |
| Branch | `feature/F08-propuesta-aprobacion` |
| Base | `origin/feature/Pipeline_RAG_PGVector` HEAD `c75b73c` (PR #64, OPEN, NOT merged to `development`) |
| Our HEAD | `2f1c477` (explore) ← `1159c46` (scaffold) |
| Rebase gate | MUST rebase onto `development` ONLY after PR #64 merges |
| Approach | **A** (relational `proposals` + `interaction_logs` + `approvals` + inline `ProposalCard` SSE) |
| Source-of-truth | `docs/adr/008-f08-proposal-approval-lifecycle.md` (this proposal mandates its creation) |

## 1. Why

Issue #12 asks for the **propuesta** phase of the arch-agent pipeline: from elicited requirements, draft an architecture proposal that cites the RAG-retrieved patterns and offers explicit Aprobar / Modificar / Rechazar controls. Acceptance criteria require (a) components/technologies/patterns in every proposal, (b) every decision MUST cite the originating RAG pattern by `pattern_id`, (c) the user MUST iterate, (d) iterations MUST be persisted in `interaction_logs` (table name is explicit). Without this phase the pipeline stops at elicitation and no `phase_ready` advance to `diseno` is possible (`openspec/config.yaml` `rules.specs` requires the approval lifecycle `proposed → approved | modified | rejected`).

## 2. What changes

| Surface | Kind | Why |
|---|---|---|
| Backend | NEW `app/api/proposals.py` | Streaming SSE endpoint `/api/proposals/generate` + `/api/proposals/{id}/decision` |
| Backend | NEW `app/core/proposal_generator.py` | RAG retrieval + structured prompt + token streaming |
| Backend | NEW `app/models/{proposal,interaction_log,approval}.py` | Source of truth is relational |
| Backend | MODIFY `app/models/__init__.py` | Register the three new models |
| DB | NEW `migrations/0008_proposals_and_logs.sql` | Three tables, idempotent `CREATE TABLE IF NOT EXISTS` |
| Frontend | NEW `frontend/src/components/proposals/{ProposalCard,ProposalActions,CitationList}.tsx` | Inline UI under streamed card |
| Frontend | NEW `frontend/src/api/proposals.ts` + `frontend/src/stores/proposalsStore.ts` | Typed REST client + Zustand (per `openspec/config.yaml` `rules.apply`) |
| Frontend | MODIFY `frontend/src/components/ChatWindow.tsx` + `frontend/src/stores/chatStore.ts` | Mount `ProposalCard` when `current_phase === "propuesta"`; tag the proposal message |
| Tests | NEW `tests/api/test_proposals.py` + `tests/api/test_interaction_logs.py` + frontend Vitest coverage | Project convention (`strict_tdd: false`, tests required) |
| Docs | NEW `docs/adr/008-f08-proposal-approval-lifecycle.md` (and MAYBE `009-sse-streaming-reuse.md`) | Lock the lifecycle + SSE contract |
| Config | NONE | `.env.example` untouched |

**Why A, not B/C**: see §4.

## 3. Approach chosen (A) vs alternatives rejected

| Criterion | A — relational + inline card | B — JSONB-only | C — separate `/propuesta` page |
|---|---|---|---|
| Satisfies "iterations in `interaction_logs`" (table name) | ✅ new `interaction_logs` table | ❌ JSONB blob in `sessions.engram_state` | ✅ new table |
| Cites patterns by `pattern_id` | ✅ `proposals.citations` JSONB w/ FK | ⚠️ possible but no relational join | ✅ same |
| Review budget (`review_budget_lines: 800`) | ⚠️ ~700–900 LoC (chained PRs planned, §12) | ✅ ~400–550 LoC | ❌ ~1100–1400 LoC |
| Reuses PR #64 SSE handler | ✅ replicate pattern from `app/api/chat.py` | ✅ | ✅ |
| Rollback cleanliness | ✅ drop migration + files | ✅ trivial | ⚠️ router + page cleanup |
| **Verdict** | **CHOSEN** | REJECTED (violates literal AC) | DEFERRED (over budget; revisit after F08 lands) |

## 4. Out of scope (v1)

- Engram mirror of proposal state (relational tables are source of truth).
- Separate `/propuesta` page or `ProposalEditor` modal (Approach C).
- Cleanup of `app/models/pattern.py` duplicate of `ArchitectPattern` — left to PR #64 review.
- ADR-005 Engram-as-MCP integration for proposals.
- i18n: copy stays Spanish per existing `MessageBubble` / `PhaseBadge` convention.

## 5. Resolved ambiguities

| # | Decision | One-line rationale |
|---|---|---|
| 1 | Iterate = **regenerate-with-feedback** (new `proposals` row + previous in `approvals.previous_output`) | Matches AC "el usuario puede iterar" + seed `Modifica` semantics; preserves audit trail. |
| 2 | `interaction_logs` + `approvals` tables created now via migration `0008_*` | They do not exist; F08 owns them. `scripts/setup-local.sh` reruns idempotently. |
| 3 | "Aprobar / Modificar / Rechazar" = inline `ProposalActions` panel below streamed card | Matches chat-centric architecture; no router change. |
| 4 | Generation transport = **SSE streaming** reusing `SSEStreamCallbackHandler` + `X-Accel-Buffering: no` | Same contract as `app/api/chat.py`; no new transport. |
| 5 | Trigger = explicit "Generar propuesta" button (NOT automatic on phase entry) | Matches issue's "Punto de decisión" framing; keeps `phase_ready` semantics. |
| 6 | "Rechazar" = revert `current_phase` to `requerimientos` (configurable later) | User-friendly: re-runs elicitation instead of forcing iterations on a rejected proposal. |
| 7 | Engram integration = **out of scope v1** | Relational `proposals` is source of truth; reduces coupling. |

## 6. Affected components (paths pinned to current HEAD)

| Path | Kind |
|---|---|
| `app/api/proposals.py` | NEW |
| `app/core/proposal_generator.py` | NEW |
| `app/models/proposal.py` | NEW |
| `app/models/interaction_log.py` | NEW |
| `app/models/approval.py` | NEW |
| `app/models/__init__.py` | MODIFY (register 3 new models) |
| `migrations/0008_proposals_and_logs.sql` | NEW (idempotent) |
| `frontend/src/api/proposals.ts` | NEW |
| `frontend/src/stores/proposalsStore.ts` | NEW |
| `frontend/src/components/proposals/ProposalCard.tsx` | NEW |
| `frontend/src/components/proposals/ProposalActions.tsx` | NEW |
| `frontend/src/components/proposals/CitationList.tsx` | NEW |
| `frontend/src/components/ChatWindow.tsx` | MODIFY |
| `frontend/src/stores/chatStore.ts` | MODIFY (minimal) |
| `tests/api/test_proposals.py` | NEW |
| `tests/api/test_interaction_logs.py` | NEW |
| `frontend/src/components/proposals/__tests__/*.test.tsx` | NEW |
| `docs/adr/008-f08-proposal-approval-lifecycle.md` | NEW |

## 7. Stack dependency on PR #64

F08 imports (read-only) the following symbols from PR #64 HEAD `c75b73c`:

| Symbol | Source (verified in explore) | Used by |
|---|---|---|
| `similarity_search(scope="patterns", k=5)` | `app/core/rag.py` (PR #64) | `proposal_generator` |
| `ArchitectPattern` (table `architect_patterns`) | `app/models/architect_pattern.py` (PR #64) | `proposals.citations` FK target |
| `RAG_MIN_SIMILARITY = 0.85` constant semantics | `app/api/chat.py` (PR #64) | threshold reuse |
| `SSEStreamCallbackHandler` + `X-Accel-Buffering: no` | `app/api/chat.py` (PR #64) | SSE replication |
| `scripts/seed_patterns.py` 11 patterns | PR #64 | test fixtures for citation IDs |

**Rebase plan**: rebased ONLY after PR #64 merges to `development`. Until then, base stays `c75b73c`. If PR #64 renames any imported symbol before merge, this proposal MUST be re-opened (status `blocked`).

## 8. Success criteria (mapped to issue #12 ACs)

| Issue AC | Scenario (Given/When/Then) |
|---|---|
| La propuesta incluye componentes, tecnologías y patrones | **GIVEN** elicitación completa y `phase_ready=true` **WHEN** user clicks "Generar propuesta" **THEN** streamed markdown SHALL contain sections "Componentes", "Tecnologías", "Patrones" (RFC 2119 MUST). |
| Cada decisión cita el patrón del RAG | **WHEN** the stream finishes **THEN** every "Patrón:" line SHALL reference `architect_patterns.id` via `proposals.citations` (JSONB) and render a `CitationList` entry with `pattern_name` + similarity score (RFC 2119 MUST). |
| El usuario puede iterar sobre la propuesta | **WHEN** user clicks "Modificar" with feedback text **THEN** a new `proposals` row (incremented `iteration`) SHALL be generated and the previous one preserved in `approvals.previous_output` (RFC 2119 MUST). |
| Las iteraciones se registran en `interaction_logs` | **THEN** each generation (initial or iterate) SHALL insert one `interaction_logs` row with `phase='propuesta'`, prompt, response, model, tokens_used, latency_ms (RFC 2119 MUST). |
| Aprobar / Rechazar phase advance | **WHEN** decision=`approved` **THEN** `phase_ready=true` and lifecycle state `approved`. **WHEN** decision=`rejected` **THEN** `current_phase` reverts to `requerimientos` (RFC 2119 SHALL). |

## 9. Risks and mitigations

| Risk | L | Mitigation |
|---|---|---|
| PR #64 unmerged; imported symbols may change | High | Pin base to `c75b73c`; rebase gate after merge; ADR-008 records the import surface. |
| 800-line review budget at boundary | Med | Work-unit commits per `work-unit-commits` skill; chained PRs planned (see §12). |
| Migration 0008 collides with future PR assuming tables absent | Med | `CREATE TABLE IF NOT EXISTS`; ownership documented in ADR-008. |
| Schema doc vs live drift (`docs/database/schema.sql` defines sessions differently from `schema.sql`) | Med | Mirror LIVE schema (user-owned sessions, project nullable) per `app/models/session.py`. |
| "Rechazar" semantics mismatch (product expectation) | Med | Configurable constant `PROPOSAL_REJECT_REVERTS_TO` in `app/core/proposal_generator.py` (defaults to `requerimientos`). |
| LLM token cost on iteration loops | Med | Cap `iteration` per project (configurable, default 5); surface count in `ProposalActions`. |
| SSE proxy buffering breaks streaming | Low | Reuse `X-Accel-Buffering: no` headers from `app/api/chat.py`. |
| Engram unavailable | Low | Engram is NOT source of truth; F08 proceeds. Topic-key persistence is best-effort. |

## 10. Rollback plan

1. **DB**: `DROP TABLE IF EXISTS interaction_logs, approvals, proposals CASCADE;` (all created by migration 0008). `run_migrations.py` is idempotent — re-running `scripts/setup-local.sh` after rollback is safe because tables were created with `IF NOT EXISTS`.
2. **Backend**: delete `app/api/proposals.py`, `app/core/proposal_generator.py`, `app/models/{proposal,interaction_log,approval}.py`, and remove the three `import` lines from `app/models/__init__.py`.
3. **Frontend**: revert `frontend/src/components/ChatWindow.tsx` and `frontend/src/stores/chatStore.ts`; delete `frontend/src/components/proposals/*` and `frontend/src/{api,stores}/proposals*`.
4. **Tests**: delete `tests/api/test_proposals.py` + `tests/api/test_interaction_logs.py` + frontend test files.
5. **Docs**: keep ADR-008 in `docs/adr/` (records the lifecycle decision even if reverted — historical record per `openspec/config.yaml` `rules.archive`).
6. **PR reverts cleanly** — every new file is independently deletable; no shared table or symbol touches PR #64 surface.

## 11. Delivery plan (chained PRs)

Approach A is ~700–900 LoC vs `review_budget_lines: 800` (session preflight). Plan to slice into chained PRs using **stacked-to-main** (`chain_strategy` to be confirmed in `sdd-tasks`; natural default given PR #64 itself is stacked):

| Slice | Scope | Est. LoC | Verifies |
|---|---|---|---|
| **#1 — backend core** | `migrations/0008_*` + `app/models/{proposal,interaction_log,approval}.py` + `app/core/proposal_generator.py` (non-streaming `generate_sync()`) + `tests/api/test_proposals.py` + `tests/api/test_interaction_logs.py` + ADR-008 | ~450 | `pytest tests/api/test_proposals.py tests/api/test_interaction_logs.py` |
| **#2 — SSE + frontend** | `app/api/proposals.py` (streaming + decision endpoint) + `frontend/src/{api,stores}/proposals*` + `frontend/src/components/proposals/*` + `ChatWindow.tsx` mount + frontend Vitest | ~300–350 | `cd frontend && npm run test:run && npm run build` |

Each slice MUST be a single PR reviewable in ≤60 min per `chained-pr` skill. Rebase `#2` onto `development` after PR #64 merges AND after `#1` lands.

## 12. ADRs to add

| ADR | Title | Status | Owner |
|---|---|---|---|
| **008** | F08 — relational source of truth for proposals (rejecting JSONB-only) | NEW — MANDATORY | Daniel |
| 009 (optional) | SSE streaming pattern reuse (lock `SSEStreamCallbackHandler` + `X-Accel-Buffering: no` as canonical) | MAYBE — decided in `sdd-design` | Daniel |

Existing ADR-001 (`LangChain framework`) and ADR-002 (`PostgreSQL + PGVector`) and ADR-004 (`Langfuse observability`) are referenced unchanged.

## 13. References

- Explore: `openspec/changes/F08-propuesta-aprobacion/explore.md` @ `2f1c477` (this branch).
- Issue #12: <https://github.com/danielCH26/arch-agent/issues/12>.
- PR #64 base: `c75b73c` on `origin/feature/Pipeline_RAG_PGVector`.
- Project config: `openspec/config.yaml` (`rules.specs` mandates the approval lifecycle; `rules.design` mandates stackable on PR #64).
- ADRs: `docs/adr/{001,002,004,005}.md`.
- Schemas: live `schema.sql`; legacy doc `docs/database/schema.sql` (NOT authoritative).