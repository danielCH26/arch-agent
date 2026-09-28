# Tasks: HU10 v2 — Per-stage approval gate with project scoping

> Change: `hu10-staged-approvals-v2` · Base: `development` (NEVER PR #78 head, NEVER main) · New branch: `feature/hu10-staged-approvals-v2` · PR scope: <= 800 changed lines (additions + deletions, excluding goldens) · Delivery strategy: `single-pr`

## Review Workload Forecast

| Field | Value |
|---|---|
| Forecasted changed lines | ~1,251 |
| Forecasted files | ~18 |
| 400-line budget risk | High |
| 800-line budget risk | High |
| Chained PRs recommended | Yes (forced by forecast) |
| Chain strategy | pending user decision |
| Decision needed before apply | Yes |

### Plain-text guard lines (REQUIRED)

```
Decision needed before apply: Yes
Chained PRs recommended: Yes
400-line budget risk: High
800-line budget risk: High
```

Per cached `delivery_strategy: single-pr`, the change MUST split into chained PRs unless the user accepts `size:exception`. Recommend chained PRs from `feature/hu10-tracker` (hub-and-spoke). Each PR has its own focused test command, runtime harness, and rollback boundary (see Commit boundary plan below).

## Pre-implementation (PR-0)

### 0.1 Create fresh branch from development
- Files: `git checkout development && git pull origin development && git checkout -b feature/hu10-staged-approvals-v2`
- Verify: `git log --oneline -1` shows development tip; `git status` clean
- Coverage: N/A · Runtime harness: N/A · Rollback: `git branch -D feature/hu10-staged-approvals-v2`
- Reason: avoids cherry-pick of v1's 18.3k LoC scope creep

### 0.2 Confirm v1 files do NOT exist on base
- Verify: `git ls-files | grep -E '(phase_decisions\.py|PhaseActions\.tsx|approvalsStore\.ts)'` returns 0 hits
- Coverage: N/A · Runtime harness: N/A · Rollback: N/A
- Reason: treats v1 files as net-new

## Backend tasks

### 1. Migration 0017

#### 1.1 Write migration SQL
- Files: `migrations/0017_add_project_id_to_approvals.sql`
- Content: `ADD COLUMN IF NOT EXISTS project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE;` + backfill from `sessions.project_id` + `CREATE INDEX IF NOT EXISTS ix_approvals_project_phase_created ON approvals (project_id, phase, created_at DESC);` + `DROP INDEX IF EXISTS idx_approvals_session_phase_created;`
- Verify: `python migrations/run_migrations.py` reports "No hay migraciones pendientes" on second run
- Coverage: N/A · Runtime harness: `docker compose up -d postgres-app && python migrations/run_migrations.py`
- Rollback: `DROP COLUMN project_id;` + recreate session index · Implements: REQ-SA-27

#### 1.2 Mirror schema in schema.sql
- Files: `schema.sql`
- Verify: `grep -A3 'project_id' schema.sql` shows column + index inside `approvals` CREATE TABLE block
- Coverage: N/A · Runtime harness: `python scripts/init_db.py` then `\d approvals` shows `project_id`
- Rollback: revert · Implements: REQ-SA-27 (init-db path)

### 2. Approval model

#### 2.1 Extend `app/models/approval.py`
- Files: `app/models/approval.py`
- Verify: `python -c "from app.models.approval import Approval; print(Approval.project_id.type)"` exits 0
- Coverage: N/A · Runtime harness: `pytest tests/models/test_approval.py -v` (Postgres)
- Rollback: revert · Implements: REQ-SA-27

#### 2.2 Tests for model extension
- Files: `tests/models/test_approval.py`
- Verify: `pytest tests/models/test_approval.py -v` passes; asserts `project_id` required and FK cascade on delete
- Coverage: >=90% line · Runtime harness: same as 2.1
- Rollback: revert · Implements: REQ-SA-27

### 3. Domain helper `phase_decisions.py`

#### 3.1 Rewrite `record_decision`
- Files: `app/core/phase_decisions.py` (net-new on development)
- Verify: `pytest tests/core/test_phase_decisions.py -v` passes; covers project_id filter, FOR UPDATE, current_phase check, payload-hash idempotency
- Coverage: >=95% (per design Test Plan)
- Runtime harness: `docker compose up -d postgres-app && pytest tests/core/test_phase_decisions.py -v` (Postgres required — SQLite false-passes on FOR UPDATE)
- Rollback: revert · Implements: REQ-SA-27, REQ-SA-28, REQ-SA-30, REQ-SA-33, REQ-SA-34

#### 3.2 Postgres-backed concurrency test
- Files: `tests/core/test_phase_decisions_concurrency.py` (new)
- Verify: `pytest tests/core/test_phase_decisions_concurrency.py -v` passes; N concurrent calls; exactly one INSERT wins, others 409
- Coverage: N/A · Runtime harness: same as 3.1
- Rollback: revert · Implements: REQ-SA-31

#### 3.3 Remove `get_latest_decision`
- Files: `app/core/phase_decisions.py`
- Verify: `grep -rn 'get_latest_decision' app/ frontend/ tests/` returns 0 hits
- Coverage: N/A · Runtime harness: N/A (grep)
- Rollback: revert · Implements: REQ-SA-35

#### 3.4 Audit log carries project_id
- Files: `app/core/phase_decisions.py`
- Verify: `pytest tests/core/test_phase_decisions.py::TestAuditLog -v` passes; `project_id` in interaction_log metadata
- Coverage: N/A · Runtime harness: same as 3.1
- Rollback: revert · Implements: REQ-SA-34

### 4. API endpoints

#### 4.1 Extend `GET /api/projects/{id}/phases`
- Files: `app/api/projects.py`
- Verify: `pytest tests/api/test_phases_endpoint.py -v` passes; response includes `pending_decision` per phase and top-level
- Coverage: >=90% · Runtime harness: `docker compose up -d backend postgres-app && curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/projects/1/phases | jq` shows `pending_decision`
- Rollback: revert · Implements: REQ-SA-12, REQ-SA-26

#### 4.2 Typed 409 for POST /decision
- Files: `app/api/projects.py` (decision route)
- Verify: `pytest tests/api/test_decision_endpoint.py -v` passes; `phase_mismatch` test asserts 409 with `detail.error=phase_mismatch` and `current_phase`
- Coverage: >=90% · Runtime harness: `curl -X POST -H "Authorization: Bearer $TOKEN" -d '{"action":"approve"}' http://localhost:8000/api/projects/1/phase/final/decision` when project in `requerimientos` returns 409
- Rollback: revert · Implements: REQ-SA-9, REQ-SA-28, REQ-SA-34

#### 4.3 `/advance` enforces single-owner
- Files: `app/api/projects.py`
- Verify: `pytest tests/api/test_advance_endpoint.py -v` passes; advance without HU10 approval for `propuesta` returns 409
- Coverage: >=90% · Runtime harness: `curl -X POST -H "Authorization: Bearer $TOKEN" /api/projects/1/advance` with no prior approval returns 409
- Rollback: revert · Implements: REQ-SA-36

### 5. End-to-end smoke

#### 5.1 Walk 5 phases with mocked LLM
- Files: `tests/e2e/test_hu10_walk.py` (new)
- Verify: `pytest tests/e2e/test_hu10_walk.py -v` passes; httpx + mocked chat; verifies `pending_decision` in `/phases` and 409 on phase_mismatch
- Coverage: N/A · Runtime harness: `docker compose up -d backend postgres-app && pytest tests/e2e/test_hu10_walk.py -v`
- Rollback: revert · Implements: REQ-SA-26 server side

## Frontend tasks

### 6. Error parsing fix

#### 6.1 Read err.data.detail.*
- Files: `frontend/src/stores/approvals.ts`
- Verify: `npm run test:run -- approvals.test.ts` passes; tolerates both `err.data?.detail` and legacy `err.data`
- Coverage: N/A · Runtime harness: `npm run dev` + browser: trigger 409, confirm typed `ApiConflictError`
- Rollback: revert · Implements: REQ-SA-29

#### 6.2 Integration test with real HTTP error shape
- Files: `frontend/src/stores/__tests__/approvals.integration.test.ts` (new)
- Verify: `npm run test:run -- approvals.integration.test.ts` passes; vi.mock on `apiFetch` returns FastAPI 409 body; asserts `current_decision` surface
- Coverage: N/A · Runtime harness: same as 6.1
- Rollback: revert · Implements: REQ-SA-29

### 7. PhaseActions component fixes

#### 7.1 text-white on Aprobar button
- Files: `frontend/src/components/PhaseActions/PhaseActions.tsx`
- Verify: `npm run test:run -- PhaseActions.test.tsx` passes; visual: green button text readable
- Coverage: N/A · Runtime harness: `npm run dev` + browser check
- Rollback: revert · Implements: v1 minor finding

#### 7.2 Replace window.prompt with RejectDialog
- Files: `frontend/src/components/PhaseActions/PhaseActions.tsx` + new `frontend/src/components/PhaseActions/RejectDialog.tsx`
- Verify: `npm run test:run -- RejectDialog.test.tsx PhaseActions.test.tsx` passes; Cancel fires no request
- Coverage: N/A · Runtime harness: browser click Rechazar opens dialog; click Cancel makes zero network calls
- Rollback: revert · Implements: REQ-SA-32

### 8. ChatWindow mount logic

#### 8.1 Mount PhaseActions from /phases
- Files: `frontend/src/components/ChatWindow.tsx` + new `frontend/src/api/phases.ts`
- Verify: `npm run test:run -- ChatWindow.test.tsx phases.test.ts` passes; on mount and after each chat response, `getPhases` called and `pendingDecision` set in store
- Coverage: N/A · Runtime harness: `npm run dev` + browser: confirm `<PhaseActions/>` renders from /phases path even with SSE disconnected
- Rollback: revert · Implements: REQ-SA-26

### 9. Frontend smoke

#### 9.1 Build + bundle
- Files: N/A · Verify: `cd frontend && npm run build` exits 0; no TS errors
- Coverage: N/A · Runtime harness: N/A (build)
- Rollback: revert · Implements: general

## Documentation tasks

### 10. ADR-015 successor

#### 10.1 Write ADR-015
- Files: `docs/adr/015-hu10-phase-gate-v2.md`
- Verify: `ls docs/adr/015*` exists; follows ADR template per init obs #17; covers project_id ownership, race policy, idempotency, single-owner table
- Coverage: N/A · Runtime harness: N/A (docs) · Rollback: revert
- Implements: ADR-015 successor

#### 10.2 Update ADR-014 status
- Files: `docs/adr/014-hu10-phase-gate.md`
- Verify: `head -5 docs/adr/014-hu10-phase-gate.md` shows "Status: Superseded by ADR-015 (2026-09-27)"
- Coverage: N/A · Runtime harness: N/A · Rollback: revert
- Implements: traceability

## Commit boundary plan

If user accepts chained PRs (recommended): PR #1 = WU-1; PR #2 = WU-2; PR #3 = WU-3; PR #4 = WU-4; PR #5 = WU-5.

If `size:exception` for single PR, 10 sequential commits: (1) migration(approvals): add project_id + drop legacy index (0017); (2) model(approval): require project_id FK; (3) feat(phase-decisions): project_id filter, FOR UPDATE, current_phase check, payload-hash idempotency; (4) feat(phase-decisions): Postgres-backed concurrency test; (5) feat(api): GET /phases pending_decision; POST /decision typed 409; (6) feat(api): /advance enforces single-owner; (7) fix(frontend): approvals.ts reads err.data.detail.*; (8) feat(frontend): RejectDialog + PhaseActions text-white; (9) feat(frontend): ChatWindow mounts from /phases; (10) docs(adr-015): record v2 contract.

## Risk register

| Task | Risk | Mitigation |
|---|---|---|
| 1.1 | Migration fails mid-apply | Idempotent; rollback = DROP COLUMN |
| 3.1 | Race regression if SQLite | Task 3.2 Postgres-backed test; CI gate |
| 4.2 | Frontend error parsing not updated | Tasks 6.1 + 6.2 in same chain slice |
| 8.1 | SSE / /phases drift | /phases is source of truth |
| 5.1 | E2E requires real LLM | Mocked chat; real-LLM smoke documented |

## Open decisions for the user

1. Single-PR vs chained PRs: forecast ~1,251 lines exceeds 800 budget. Recommend chained PRs. Otherwise user must accept `size:exception`.
2. Deprecation window for `previous_output` alias: 1 release (per REQ-SA-33). Confirm.
3. Idempotency-Key header vs server-only derivation: server-only with optional client advisory (REQ-SA-30). Confirm.
4. `pending_decision` in both `/phases` and SSE `phase_locked`: design assumes BOTH (REQ-SA-26). Confirm.
