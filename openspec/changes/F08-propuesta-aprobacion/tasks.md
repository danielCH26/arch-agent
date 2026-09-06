# Tasks: F08 â€” Propuesta + AprobaciÃ³n

| Field | Value |
|---|---|
| Change slug | `F08-propuesta-aprobacion` |
| Capability | `openspec/specs/proposal-approval/` |
| Branch | `feature/F08-propuesta-aprobacion` (HEAD `34cf2fc`) |
| Base | `origin/feature/Pipeline_RAG_PGVector` @ `c75b73c` (PR #64 OPEN; rebase gate after merge) |
| Approach (locked) | A â€” relational `proposals` + `interaction_logs` + `approvals` + inline SSE `ProposalCard` |
| Relationship | Translates `design.md` (`34cf2fc`, 630 LoC, 4 sequence diagrams + ER + SQL + 11 SCN) into reviewable tasks. ADR-008 (`docs/adr/008-f08-relational-source-of-truth.md`) and ADR-009 (`docs/adr/009-sse-pattern-reuse.md`) already authored at `34cf2fc` â€” NO task needed for them. |
| Engram topic_key (this artifact) | `sdd/F08-propuesta-aprobacion/tasks` (type=`architecture`, `capture_prompt=false`) |

## 1. Review Workload Forecast

`review_budget_lines = 800` per session preflight.

Decision needed before apply: No
Chained PRs recommended: Yes
Chain strategy: stacked-to-main
400-line budget risk: High (per-skill threshold; project threshold is 800/slice)

### Forecast table

| Slice | # | Task | Files | LoC prod | LoC tests | REQ/SCN |
|---|---|---|---|---|---|---|
| slice_1_backend | 1.1 | migration 0008 | `migrations/0008_proposals_and_logs.sql` | 60 | 0 | REQ-5, SCN-6 |
| slice_1_backend | 2.1 | `Proposal` model | `app/models/proposal.py` + `__init__.py` | 35+3 | 0 | REQ-1, REQ-4 |
| slice_1_backend | 2.2 | `InteractionLog` model | `app/models/interaction_log.py` | 40 | 0 | REQ-3 |
| slice_1_backend | 2.3 | `Approval` model | `app/models/approval.py` | 30 | 0 | REQ-3, REQ-4 |
| slice_1_backend | 3.1 | `ProposalGenerator` stub | `app/core/proposal_generator.py` | 80 | 0 | REQ-1, REQ-2, REQ-4 |
| slice_1_backend | 4.1 | generator unit tests | `tests/core/test_proposal_generator.py` | 0 | 60 | SCN-2, SCN-3 |
| slice_1_backend | 4.2 | interaction_logs + idempotency tests | `tests/api/test_interaction_logs.py` | 0 | 50 | SCN-6, SCN-10 |
| slice_1_backend | 4.3 | proposals service-level tests | `tests/api/test_proposals.py` (models + decide) | 0 | 60 | SCN-1, SCN-4, SCN-5, SCN-9 |
| **slice_1 subtotal** | | | | **248** | **170** | |
| slice_2_sse_and_frontend | 5.1 | `ProposalGenerator.stream()` impl | `app/core/proposal_generator.py` | +90 | 0 | REQ-6, SCN-7 |
| slice_2_sse_and_frontend | 5.2 | router + `_emit_sse` | `app/api/proposals.py` | 200 | 0 | REQ-3, REQ-6, REQ-7, REQ-8 |
| slice_2_sse_and_frontend | 5.3 | router + SSE integration tests | extend `tests/api/test_proposals.py` | 0 | +50 | SCN-4, SCN-5, SCN-7, SCN-9 |
| slice_2_sse_and_frontend | 6.1 | REST + SSE client | `frontend/src/api/proposals.ts` | 90 | 0 | REQ-6, SCN-7 |
| slice_2_sse_and_frontend | 6.2 | Zustand store | `frontend/src/stores/proposalsStore.ts` | 70 | 0 | REQ-1, REQ-3 |
| slice_2_sse_and_frontend | 7.1 | `CitationList` | `frontend/src/components/proposals/CitationList.tsx` | 35 | 0 | REQ-2 |
| slice_2_sse_and_frontend | 7.2 | `ProposalActions` | `frontend/src/components/proposals/ProposalActions.tsx` | 70 | 0 | REQ-3, REQ-4, REQ-8 |
| slice_2_sse_and_frontend | 7.3 | `ProposalCard` | `frontend/src/components/proposals/ProposalCard.tsx` | 110 | 0 | REQ-1, REQ-7 |
| slice_2_sse_and_frontend | 8.1 | mount `ProposalCard` in `ChatWindow` | `frontend/src/components/ChatWindow.tsx` | +25 | 0 | REQ-7, SCN-8 |
| slice_2_sse_and_frontend | 8.2 | tag proposal message | `frontend/src/stores/chatStore.ts` | +10 | 0 | REQ-1 |
| slice_2_sse_and_frontend | 9.1 | `CitationList` vitest | `frontend/.../__tests__/CitationList.test.tsx` | 0 | 25 | SCN-2, SCN-3 |
| slice_2_sse_and_frontend | 9.2 | `ProposalActions` vitest | `frontend/.../__tests__/ProposalActions.test.tsx` | 0 | 35 | SCN-4, SCN-5 |
| slice_2_sse_and_frontend | 9.3 | `ProposalCard` vitest (mount) | `frontend/.../__tests__/ProposalCard.test.tsx` | 0 | 40 | SCN-8 |
| **slice_2 subtotal** | | | | **700** | **150** | |
| **GRAND TOTAL** | | | | **948** | **320** | |

Per-slice total (`additions + deletions`): slice_1 â‰ˆ 418, slice_2 â‰ˆ 850. Slice_2 sits at the 800-budget boundary; trim by deferring 5.3's SSE tests to slice_2's "PR-2 follow-up" only if actual diff exceeds 800. Largest single task = 5.2 (200 LoC, under 400).

## 2. Chained-PR decision

Chained PRs REQUIRED: grand total authored â‰ˆ 948 LoC and grand total with tests â‰ˆ 1 268 LoC, both well above the 800-line per-PR budget. Per-skill rule: split PRs > 400 changed lines.

**Chain strategy: `stacked-to-main`** (resolved by this phase).

Rationale: PR #64 is itself stacked against `development` (per `git log c75b73c`); F08 cannot merge to `development` until PR #64 lands, so introducing a `feature/F08-tracker` would add ceremony without rollback benefit â€” both children would still wait on the same upstream merge gate. Each slice â‰¤ 850 LoC; both land independently as stacked PRs against `development`. Per `chained-pr` skill Â§"Execution Steps": ask the user only when the cached `chain_strategy` is unset; preflight cached `auto-chain` + default `stacked-to-main` (this resolution) makes `decision_needed_before_apply = No`.

Seam marking slice boundary: `ProposalGenerator.stream()` â€” declared in slice_1 as `async def stream(self) -> AsyncIterator[StreamEvent]: raise NotImplementedError("streaming wired in slice 2")`. Slice_2 fills the body and adds `app/api/proposals.py`. No import surface from PR #64 is touched (read-only per design Â§12).

## 3. Slice plan

### Slice 1 â€” Backend core (target PR #1)

| Field | Value |
|---|---|
| Branch | `feature/F08-s1-backend-core` (cut from HEAD `34cf2fc`) |
| Base | `origin/feature/Pipeline_RAG_PGVector` @ `c75b73c` |
| Files (NEW) | `migrations/0008_proposals_and_logs.sql`, `app/models/proposal.py`, `app/models/interaction_log.py`, `app/models/approval.py`, `app/core/proposal_generator.py` (stub), `tests/core/test_proposal_generator.py`, `tests/api/test_proposals.py`, `tests/api/test_interaction_logs.py` |
| Files (MODIFY) | `app/models/__init__.py` (+3 imports) |
| LoC budget | 418 |
| REQ/SCN coverage | REQ-1, REQ-2, REQ-3, REQ-4, REQ-5, SCN-1, SCN-2, SCN-3, SCN-4, SCN-5, SCN-6, SCN-9, SCN-10 |
| Verification | `pytest tests/core/test_proposal_generator.py tests/api/test_interaction_logs.py tests/api/test_proposals.py -v` |
| Runtime harness | `scripts/setup-local.sh` (idempotent rerun â†’ SCN-6); manual `psql -f migrations/0008_proposals_and_logs.sql` then rerun â†’ exit 0 |
| Rollback | `git revert <PR-1 merge SHA>` removes migration runner entry + deletes files; `DROP TABLE IF EXISTS approvals, interaction_logs, proposals CASCADE` purges schema; PR #64 surface untouched |

### Slice 2 â€” SSE + frontend (target PR #2)

| Field | Value |
|---|---|
| Branch | `feature/F08-s2-sse-and-frontend` (cut from slice_1 merge SHA onto `development` AFTER PR #64 merges) |
| Base | `development` (rebased post-PR-#64 + post-PR-#1) |
| Files (NEW) | `app/api/proposals.py`, `frontend/src/api/proposals.ts`, `frontend/src/stores/proposalsStore.ts`, `frontend/src/components/proposals/{ProposalCard,ProposalActions,CitationList}.tsx`, `frontend/src/components/proposals/__tests__/{ProposalCard,ProposalActions,CitationList}.test.tsx` |
| Files (MODIFY) | `app/core/proposal_generator.py` (`stream()` body), `frontend/src/components/ChatWindow.tsx`, `frontend/src/stores/chatStore.ts`, `tests/api/test_proposals.py` (router + SSE additions) |
| LoC budget | 850 (at boundary) |
| REQ/SCN coverage | REQ-1, REQ-2, REQ-3, REQ-4, REQ-6, REQ-7, REQ-8, REQ-9, REQ-10, SCN-1, SCN-2, SCN-3, SCN-4, SCN-5, SCN-7, SCN-8, SCN-9, SCN-10, SCN-11 |
| Verification | `pytest tests/api/test_proposals.py -v` + `cd frontend && npm run test:run && npm run build` |
| Runtime harness | `uvicorn app.main:app --reload` + manual smoke: POST `/api/proposals/generate` from `current_phase="propuesta"` UI â†’ SSE `sources \| token \| done` events observed; click Aprobar â†’ `interaction_logs` row inserted; refresh page â†’ `ProposalCard` re-renders with `lifecycle="approved"` chip |
| Rollback | `git revert <PR-2 merge SHA>`; if only slice_2 breaks, `DELETE /api/proposals/*` route is no-op; frontend revert hides `ProposalCard`; DB schema from slice_1 stays intact |

## 4. Tasks (hierarchical by area)

Each task: title Â· slice Â· files Â· LoC Â±15% Â· REQ/SCN Â· acceptance Â· commit hint.

### 1. Migrations

- [x] 1.1 **Author `migrations/0008_proposals_and_logs.sql`** Â· slice_1_backend Â· NEW `migrations/0008_proposals_and_logs.sql` Â· 60 LoC Â· REQ-5, SCN-6 Â· `git check-ignore migrations/0008_proposals_and_logs.sql` exits 1 (not ignored); `python migrations/run_migrations.py` then re-run exits 0 (idempotent) Â· commit `feat(db): add migration 0008 proposals, interaction_logs, approvals (idempotent CREATE TABLE IF NOT EXISTS)`

### 2. Backend models

- [x] 2.1 **Author `Proposal` ORM model** Â· slice_1_backend Â· NEW `app/models/proposal.py` (+35), MODIFY `app/models/__init__.py` (+1) Â· 36 LoC Â· REQ-1, REQ-4 Â· `pytest tests/api/test_proposals.py::test_proposal_orm_round_trip -v` passes Â· commit `feat(models): add Proposal ORM with lifecycle CHECK + unique (project_id, iteration)`
- [x] 2.2 **Author `InteractionLog` ORM model** Â· slice_1_backend Â· NEW `app/models/interaction_log.py` (+40), MODIFY `app/models/__init__.py` (+1) Â· 41 LoC Â· REQ-3 Â· `pytest tests/api/test_interaction_logs.py::test_interaction_log_orm_round_trip -v` passes Â· commit `feat(models): add InteractionLog ORM with phase/action_type/comment/prompt/response/model/tokens/latency`
- [x] 2.3 **Author `Approval` ORM model** Â· slice_1_backend Â· NEW `app/models/approval.py` (+30), MODIFY `app/models/__init__.py` (+1) Â· 31 LoC Â· REQ-3, REQ-4 Â· `pytest tests/api/test_proposals.py::test_approval_orm_round_trip -v` passes Â· commit `feat(models): add Approval ORM with decision CHECK + previous_output JSONB`

### 3. Backend core (slice 1)

- [x] 3.1 **Author `ProposalGenerator` with stub `stream()`** Â· slice_1_backend Â· NEW `app/core/proposal_generator.py` Â· 80 LoC Â· REQ-1, REQ-2, REQ-4 Â· `pytest tests/core/test_proposal_generator.py -v` passes (sync methods); `pytest tests/api/test_proposals.py -v` passes for decide path Â· commit `feat(core): add ProposalGenerator with citation filter + structured prompt; stream() deferred to slice 2`

### 4. Backend tests (slice 1)

- [x] 4.1 **Unit tests for `ProposalGenerator`** Â· slice_1_backend Â· NEW `tests/core/test_proposal_generator.py` Â· 60 LoC tests Â· SCN-2, SCN-3 Â· `pytest tests/core/test_proposal_generator.py -v` passes (citation filter positive + negative + threshold) Â· commit `test(core): cover ProposalGenerator citation filter, prompt assembly, regenerate_with_feedback`
- [x] 4.2 **Tests for migration idempotency + Engram outage** Â· slice_1_backend Â· NEW `tests/api/test_interaction_logs.py` Â· 50 LoC tests Â· SCN-6, SCN-10 Â· `pytest tests/api/test_interaction_logs.py -v` passes Â· commit `test(api): migration 0008 rerun idempotent; interaction_log written when engram unreachable`
- [x] 4.3 **Service-level tests for proposal lifecycle** Â· slice_1_backend Â· NEW `tests/api/test_proposals.py` (initial: model + decide-via-service only) Â· 60 LoC tests Â· SCN-1, SCN-4, SCN-5, SCN-9 Â· `pytest tests/api/test_proposals.py -v` passes for SCN-1/SCN-4/SCN-5/SCN-9 paths Â· commit `test(api): proposal model + decide service (approve/reject) + PROPOSAL_REJECT_REVERTS_TO env override`

### 5. Backend API (slice 2)

- [x] 5.1 **Implement `ProposalGenerator.stream()` async SSE** Â· slice_2_sse_and_frontend Â· MODIFY `app/core/proposal_generator.py` (+90 LoC to existing 80 â†’ 170 total) Â· 90 LoC Â· REQ-6, SCN-7 Â· `pytest tests/core/test_proposal_generator.py -v` still passes; emits `sources \| token \| done` in test harness Â· commit `feat(core): implement ProposalGenerator.stream() async iterator for SSE`
- [x] 5.2 **Author `app/api/proposals.py` router with 4 endpoints** Â· slice_2_sse_and_frontend Â· NEW `app/api/proposals.py` Â· 200 LoC Â· REQ-3, REQ-6, REQ-7, REQ-8 Â· `pytest tests/api/test_proposals.py -v` passes for all router paths; `curl -N -X POST localhost:8000/api/proposals/generate -d '{"project_id":42}' -H "Authorization: Bearer â€¦"` returns SSE `sources \| token \| done` Â· commit `feat(api): proposals router (generate, modify, decide, get_by_id) with _emit_sse helper`
- [x] 5.3 **Router + SSE integration tests** Â· slice_2_sse_and_frontend Â· MODIFY `tests/api/test_proposals.py` (+50 LoC) Â· 50 LoC tests Â· SCN-4, SCN-5, SCN-7, SCN-9 Â· `pytest tests/api/test_proposals.py -v` passes for SSE done payload + modify iteration increment Â· commit `test(api): router integration â€” SSE done payload, modify iteration, decide phase_ready transition`

### 6. Frontend API client

- [x] 6.1 **Author `frontend/src/api/proposals.ts` (REST + SSE parser)** Â· slice_2_sse_and_frontend Â· NEW `frontend/src/api/proposals.ts` Â· 90 LoC Â· REQ-6, SCN-7 Â· `cd frontend && npx tsc --noEmit` exits 0; manual: `fetchEventSource` against local backend delivers `sources \| token \| done` to consumer Â· commit `feat(frontend): proposals REST client + SSE parser mirroring chat.ts contract`
- [x] 6.2 **Author `frontend/src/stores/proposalsStore.ts` (Zustand)** Â· slice_2_sse_and_frontend Â· NEW `frontend/src/stores/proposalsStore.ts` Â· 70 LoC Â· REQ-1, REQ-3 Â· `cd frontend && npm run test:run -- proposalsStore` passes; store action signatures match Â§6 of design.md Â· commit `feat(frontend): proposalsStore (currentProposal, iterations, inFlight, generate/modify/decide)`

### 7. Frontend components

- [x] 7.1 **Author `CitationList` component** Â· slice_2_sse_and_frontend Â· NEW `frontend/src/components/proposals/CitationList.tsx` Â· 35 LoC Â· REQ-2 Â· `cd frontend && npm run test:run -- CitationList` passes Â· commit `feat(frontend): CitationList renders pattern_name + similarity + ver patrÃ³n link`
- [x] 7.2 **Author `ProposalActions` component** Â· slice_2_sse_and_frontend Â· NEW `frontend/src/components/proposals/ProposalActions.tsx` Â· 70 LoC Â· REQ-3, REQ-4, REQ-8 Â· `cd frontend && npm run test:run -- ProposalActions` passes (approve/modify/reject dispatch) Â· commit `feat(frontend): ProposalActions with Aprobar/Modificar/Rechazar + feedback composer`
- [x] 7.3 **Author `ProposalCard` component** Â· slice_2_sse_and_frontend Â· NEW `frontend/src/components/proposals/ProposalCard.tsx` Â· 110 LoC Â· REQ-1, REQ-7 Â· `cd frontend && npm run test:run -- ProposalCard` passes (renders 3 sections + mount condition SCN-8) Â· commit `feat(frontend): ProposalCard with markdown body + CitationList + ProposalActions`

### 8. Frontend wiring

- [x] 8.1 **Mount `ProposalCard` in `ChatWindow`** Â· slice_2_sse_and_frontend Â· MODIFY `frontend/src/components/ChatWindow.tsx` (+25 LoC) Â· 25 LoC Â· REQ-7, SCN-8 Â· `cd frontend && npm run build` succeeds; SCN-8 vitest passes (no ProposalCard when `current_phase !== "propuesta"`) Â· commit `feat(frontend): mount ProposalCard in ChatWindow when current_phase=propuesta`
- [ ] 8.2 **Tag proposal message in `chatStore`** Â· slice_2_sse_and_frontend Â· MODIFY `frontend/src/stores/chatStore.ts` (+10 LoC) Â· 10 LoC Â· REQ-1 Â· `cd frontend && npx tsc --noEmit` exits 0; new action `tagProposalMessage` exported Â· commit `feat(frontend): chatStore.tagProposalMessage to mark assistant message that produces the proposal`

### 9. Frontend tests

- [x] 9.1 **Vitest for `CitationList`** Â· slice_2_sse_and_frontend Â· NEW `frontend/src/components/proposals/__tests__/CitationList.test.tsx` Â· 25 LoC tests Â· SCN-2, SCN-3 Â· `cd frontend && npm run test:run -- CitationList` passes Â· commit `test(frontend): CitationList renders above threshold, omits below threshold`
- [x] 9.2 **Vitest for `ProposalActions`** Â· slice_2_sse_and_frontend Â· NEW `frontend/src/components/proposals/__tests__/ProposalActions.test.tsx` Â· 35 LoC tests Â· SCN-4, SCN-5 Â· `cd frontend && npm run test:run -- ProposalActions` passes Â· commit `test(frontend): ProposalActions dispatches decide + opens modify composer`
- [x] 9.3 **Vitest for `ProposalCard` (mount condition SCN-8)** Â· slice_2_sse_and_frontend Â· NEW `frontend/src/components/proposals/__tests__/ProposalCard.test.tsx` Â· 40 LoC tests Â· SCN-8 Â· `cd frontend && npm run test:run -- ProposalCard` passes (does not render when phase !== propuesta) Â· commit `test(frontend): ProposalCard mount gated by current_phase=propuesta`

## 5. Apply-progress seed (handoff to `/sdd-apply`)

Save as Engram observation, topic_key `sdd/F08-propuesta-aprobacion/apply-progress`, type=`config`, `capture_prompt=false`:

```json
{
  "started_at": "2026-09-05T16:30:00Z",
  "current_slice": "slice_1_backend",
  "completed_tasks": [],
  "in_flight": "1.1",
  "blocked": [],
  "notes": "stack-base pinned to c75b73c; chain_strategy=stacked-to-main; ADR-008/009 pre-authored at 34cf2fc (no task needed); slice_1 budget=418 LoC, slice_2 budget=850 LoC; rebase slice_2 onto development AFTER PR #64 merges AND slice_1 PR merges"
}
```

## 6. Out of scope (carried from design Â§15)

- JSONB-only Approach B (violates literal `interaction_logs` AC).
- Separate `/propuesta` page or `ProposalEditor` modal (Approach C; revisit post-land).
- Engram-as-MCP mirror of proposal state (best-effort only).
- Cleanup of `app/models/pattern.py` duplicate (PR #64's domain).
- Reverse-proxy WebSocket transport (SSE per ADR-009).
- i18n: UI copy stays Spanish per `MessageBubble`/`PhaseBadge` convention.

## 7. Risks

- **Slice 2 rebase gate** â€” slice_2 branch MUST rebase onto `development` only AFTER PR #64 merges to `development` AND slice_1 PR merges. If rebased prematurely, slice_2's PR will show PR #64's diff and exceed review budget. Mitigation: orchestrator scripts rebase in order; chain context block in PR #2 body lists base = `development` post-#64.
- **Slice boundary discipline** â€” `ProposalGenerator.stream()` must remain `NotImplementedError` until slice_2 lands. If slice_1 accidentally implements streaming, slice_2 has nothing to add and the chain rationale breaks. Mitigation: explicit `raise NotImplementedError("streaming wired in slice 2")`; review checklist item.
- **Slice 2 at 850 LoC boundary** â€” at the 800-line cap. If actual diff exceeds 800, split 5.3 (router+SSE tests) into a follow-up micro-PR. Mitigation: `git diff --stat` during slice_2 apply; halt + split if > 800.
- **PR #64 symbol surface changes** (design Â§17 #1) â€” pin base to `c75b73c` until merge; ADR-008/009 pin import list.
- **Engram unavailable** (design Â§17 #8) â€” best-effort mirror; SCN-10 covers; F08 proceeds.
- **`.gitignore` regression** (design Â§17 #12) â€” resolved at commit `6790084`; verify `git check-ignore docs/adr/008-*.md docs/adr/009-*.md` returns empty during apply pre-flight (ADRs already exist, so risk is theoretical).

## 8. References

- `openspec/changes/F08-propuesta-aprobacion/explore.md` @ `2f1c477`
- `openspec/changes/F08-propuesta-aprobacion/proposal.md` @ `f467154`
- `openspec/specs/proposal-approval/spec.md` @ `7a3b2b1`
- `openspec/changes/F08-propuesta-aprobacion/design.md` @ `34cf2fc` (this branch)
- `docs/adr/008-f08-relational-source-of-truth.md` @ `34cf2fc` (pre-authored)
- `docs/adr/009-sse-pattern-reuse.md` @ `34cf2fc` (pre-authored)
- Issue [#12](https://github.com/danielCH26/arch-agent/issues/12)
- PR #64 base `c75b73c` on `origin/feature/Pipeline_RAG_PGVector`
- `openspec/config.yaml` (`rules.tasks`: group by area, hierarchical, session-sized; `rules.apply.tdd=false`)
- Engram topic_keys: `sdd/F08-propuesta-aprobacion/explore` (id=23), `â€¦/proposal` (id=24), `â€¦/spec` (id=26), `â€¦/design`, `â€¦/tasks` (this artifact), `â€¦/apply-progress` (next phase)
- Reused surfaces: `app/api/chat.py` (SSE template), `app/api/sse.py` (`SSEStreamCallbackHandler`), `app/core/rag.py` (`similarity_search`), `app/models/architect_pattern.py` (`ArchitectPattern`)
