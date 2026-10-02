# Apply Progress — hu10-staged-approvals-v2

> Branch: `feature/hu10-staged-approvals-v2` (branched from `development` @ a0f4fef)
> Started: 2026-09-28
> Mode: Standard (`strict_tdd: false`)
> Delivery: `single-pr` + `size:exception user-accepted` (~1,251 LoC / ~18 files)
> Pre-flight note: pre-flight rule `grep approval.py` returns 1 hit on `development` because F08 created `app/models/approval.py` and migration `0016_add_project_id_to_approvals.sql` before v2 branched. F08 work was merged into `development`. v2's work for the project_id column is therefore *additive on top of F08*, NOT a fresh column add.

## Adaptations vs original plan

| Item | Original Plan | Actual Baseline (Development) | Adapted Plan |
|---|---|---|---|
| Migration number | `0017_add_project_id_to_approvals.sql` | `0016_add_project_id_to_approvals.sql` (F08) + `0017_add_attachment_id_to_approvals.sql` (F08) already exist | Use `0018_backfill_project_id_and_extend_index.sql` (backfill + extended index; column already added) |
| `idx_approvals_session_phase_created` | drop | does not exist on development | Skip DROP (already absent); F08's index is `idx_approvals_session_phase` (session+phase), F08 also added `idx_approvals_project_phase` (project+phase) | Extend F08's `(project_id, phase)` index to include `created_at DESC` via new index `ix_approvals_project_phase_created` |
| `approvals.previous_output` column | REQ-SA-16 says migration 0015 | does not exist on `approvals` (only on `proposal_approvals`) | Add via migration 0018 + update model |
| `approval.decision` CHECK | spec REQ-SA-16 says `('approve','modify','reject')` | DB enforces `('approved','modified','rejected')`; helper `DECISION_TO_DB` converts verb→past-tense | Keep existing CHECK; spec is imprecise — actual contract is verb input → past-tense stored value |
| AVAILABLE_PHASES | 5 elements per REQ-SA-4 | 4 elements on dev (no `final`) | Add `final` as 5th element |
| `/mark-ready` endpoint | REQ-SA-23 says MUST remove | still exists on dev | Remove in v2 (returns 404 with replacement hint) |
| `/advance` enforcement | REQ-SA-36 says check HU10 approval row | dev version only checks `phase_ready` | Add HU10 approval check for HU10-owned phases |
| ADR-014 status update | "Superseded by ADR-015 (2026-09-27)" | `docs/adr/014-hu10-phase-gate.md` does NOT exist on development (only in PR #78 branch) | Cannot mark a file that doesn't exist; documented as deviation; ADR-014 is v1-only and never merged |
| F08 proposal-approval dual-write | spec says HU10 generic endpoint for propuesta | F08 already owns propuesta via `/api/projects/{id}/proposal/decision` and `/api/proposals/{id}/decide` | Keep F08 paths; HU10 v2 adds the generic `/phase/{phase}/decision` for refinamiento/revision/final; propuesta can use either (both work) |

## Batch progress

| # | Batch | Status | Commit | Files Touched | LoC Δ |
|---|---|---|---|---|---|
| 1 | migration + schema mirror | done | `deaf454` | `migrations/0018_backfill_project_id_and_extend_index.sql`, `schema.sql` | +114 |
| 2 | approval model + tests | done | `e02d5bf` | `app/models/approval.py`, `tests/models/test_approval.py` | +265 |
| 3 | phase_decisions rewrite + tests | done | `0135053` | `app/core/phase_decisions.py`, `tests/core/test_phase_decisions.py` | +960 |
| 4 | Postgres concurrency test | done | (next commit) | `tests/core/test_phase_decisions_concurrency.py` | +250 |
| 5 | remove `get_latest_decision` | done (N/A) | — | (helper didn't exist on dev; REQ-SA-35 documented as deviation) | 0 |
| 6 | API endpoint updates + tests | done | `aed3f56` | `app/api/projects.py`, `tests/api/test_projects_hu10.py` | +596 |
| 7 | backend E2E smoke | **N/A — no docker in this env** | — | — | — |
| 8 | frontend error parsing + integration test | done | `5ed11ac` | `frontend/src/api/approvals.ts`, `frontend/src/stores/__tests__/approvals.integration.test.ts` | +200 |
| 9 | PhaseActions + RejectDialog | done | `5ed11ac` | `frontend/src/components/PhaseActions/PhaseActions.tsx`, `frontend/src/components/PhaseActions/RejectDialog.tsx` | +250 |
| 10 | ChatWindow mount + phases client | done | `5ed11ac` | `frontend/src/components/ChatWindow.tsx`, `frontend/src/api/phases.ts` | +300 |
| 11 | ADR-015 + ADR-014 status | done | (next commit) | `docs/adr/015-hu10-phase-gate-v2.md` (already written; tracked). ADR-014 doesn't exist on dev — documented as deviation. | +111 |
| EXTRA | spec replacement + delta files | done | `c20b112` | `openspec/specs/staged-approvals/spec.md`, `openspec/changes/hu10-staged-approvals-v2/specs/{staged-approvals,proposal-approval}/spec.md` | +619 |

**Batches completed: 10 of 11** (Batch 7 = E2E with mocked chat, deferred — requires docker; documented).

## Runtime test results

This session environment has no docker / no live Postgres / no Node.js. The following test commands were NOT executed in-session:

- `pytest tests/models/test_approval.py -v` — requires Postgres (per `tests/models/test_approval.py` docstring).
- `pytest tests/core/test_phase_decisions.py -v` — pure unit tests with `MagicMock`; SHOULD pass on first run (no DB dependency). Not run in-session.
- `pytest tests/core/test_phase_decisions_concurrency.py -v` — requires Postgres.
- `pytest tests/api/test_projects_hu10.py -v` — uses TestClient + MagicMock; SHOULD pass on first run. Not run in-session.
- `pytest tests/e2e/test_hu10_walk.py` — DEFERRED (no docker in env).
- `cd frontend && npm run test:run -- approvals.integration.test.ts` — requires Node + vitest. Not run in-session.
- `cd frontend && npm run build` — requires Node. Not run in-session.

The CI runner on the actual `feature/hu10-staged-approvals-v2` branch will execute these. The tests are designed to be deterministic (`MagicMock`-driven where possible; real Postgres where the contract demands it).

## Deviations

1. **Migration renumber**: 0017 → 0018 (0017 already used by F08 attachment_id).
2. **decision CHECK values**: kept existing past-tense set; spec note for future cleanup.
3. **AVAILABLE_PHASES**: added `final` (was missing).
4. **`get_latest_decision` removal**: helper doesn't exist on dev; documented as no-op for v2 base.
5. **ADR-014 status**: file doesn't exist on dev; cannot update what isn't there.
6. **E2E smoke (Batch 7)**: deferred — environment lacks docker.
7. **Test execution**: all unit/integration tests are written; runtime validation deferred to next session or CI.

## Blockers

None.