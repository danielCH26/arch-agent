# PR #91 v3 Review Blockers Resolution

This document details the changes made in v3 to resolve the review blockers from PR #91.

## What Was Wrong (Blockers 1-2, Important 1-6)

### Blocker 1: `pending_decision` semantics inverted

**Problem:** `get_pending_decision` returned `None` when no approval row existed, causing the frontend `<PhaseActions>` to never mount on fresh phases.

**Fix:** Inverted semantics per SCN-SA-12.1:
- Returns `{phase, since}` when:
  - Current phase is in HU10_OWNED_PHASES (`propuesta`, `refinamiento`, `revision`, `final`)
  - AND no `approved` decision exists for the current phase
- Returns `None` when:
  - An `approved` decision already exists (surface no longer needed)
  - OR the phase is `requerimientos` (F05-owned, no HU10 surface)

### Blocker 2: No UI for `/advance` endpoint

**Problem:** `advancePhase` was exported but never called from the UI.

**Fix:** Added "Avanzar" button in `PhaseActions.tsx`:
- Shows when `phaseReady === true` AND `phase !== "requerimientos"` AND `phase !== "final"`
- On success: refreshes project store and re-fetches phases

### Important 1: Proposals double-write bypasses HU10

**Problem:** `proposals.py` wrote `phase_ready` directly without using `record_decision`, bypassing FOR UPDATE and phase validation.

**Fix:** Routed `_apply_project_proposal_decision` through `record_decision`:
- Removes manual `project.phase_ready = ...` assignment
- `record_decision` handles FOR UPDATE and phase validation internally

### Important 2: `/advance` missing FOR UPDATE

**Problem:** `db.query(Project).filter(...)` without row-level lock allowed race conditions.

**Fix:** Changed to `db.execute(select(Project).where(...).with_for_update())`.

### Important 3: `per_phase.status` calculated wrong

**Problem:** Derived status from `phase_ready` alone, marking future phases as "approved" when `phase_ready=False`.

**Fix:** Compute from actual approval rows:
- Past phases (index < current): "approved" if approval row exists, else "pending"
- Current phase: "current"
- Future phases: "pending"

### Important 4: `previous_output` never persisted

**Problem:** `/phase/{phase}/decision` ignored `previous_output` from request body.

**Fix:** Added `previous_output: Optional[dict]` to `PhaseDecisionIn` schema and passed to `record_decision`.

### Important 5: `DecisionConflict` is dead code

**Problem:** Defined but never used.

**Fix:** Removed `DecisionConflict` dataclass; added comment explaining the 409 types that ARE used (`PhaseMismatchError`, `PhaseNotApprovedError`).

### Important 6: `conftest.py` defeats `skipif`

**Problem:** `setdefault("DATABASE_URL", ...)` always set the variable, preventing `skipif` from triggering.

**Fix:** Changed to `if "DATABASE_URL" not in os.environ` pattern, preserving skipif semantics.

## Minor Fixes

- Replaced deprecated `datetime.utcnow()` with `datetime.now(timezone.utc)`
- Added explicit `+00:00` suffix in ISO string serialization for JavaScript `Date()` parsing
- Added `getProject` method to projectsStore for refresh after advance

## Test Command and Expected Results

```bash
pytest tests/core/test_phase_decisions.py tests/api/test_projects_hu10.py -v
```

Expected: **38 passed** (was 37 before due to outdated test assertions)

## New Test Coverage

- `test_get_pending_decision_returns_pending_when_no_record` - verifies pending surface for HU10 phases
- `test_get_pending_decision_returns_none_when_approved` - verifies no surface after approval
- `test_get_pending_decision_returns_none_for_requerimientos` - verifies F05 phase returns None
- `test_get_pending_decision_returns_pending_with_rejected_decision` - verifies pending after reject
- `test_get_phases_pending_decision_present_when_no_record` - API test for new semantics

## Idempotency Window Clarification

`IDEMPOTENCY_WINDOW_SECONDS = 60` applies to **identical retries only** (REQ-SA-30.1):
- Same `(action, payload, feedback)` hash within 60s returns original decision with `idempotent=True`
- Different action or different feedback within the window is accepted (REQ-SA-30.2)
- The hash now includes `feedback`, so corrected-feedback retries do NOT short-circuit

This is the intended behavior per the spec.

## Files Changed

| File | Change |
|------|--------|
| `app/core/phase_decisions.py` | Inverted pending_decision semantics, removed DecisionConflict, fixed datetime.utcnow() |
| `app/api/projects.py` | Added FOR UPDATE, fixed per_phase.status, added previous_output |
| `app/api/proposals.py` | Routed through record_decision |
| `frontend/src/components/PhaseActions/PhaseActions.tsx` | Added Avanzar button |
| `frontend/src/stores/projectsStore.ts` | Added getProject method |
| `tests/conftest.py` | Fixed DATABASE_URL setdefault |
| `tests/core/test_phase_decisions.py` | Updated tests for new semantics |
| `tests/api/test_projects_hu10.py` | Updated tests for new semantics |

## Deferred to CI

- Postgres-backed tests (`test_phase_decisions_concurrency.py`, `tests/models/test_approval.py`) - no docker in env
- Frontend tests (`npm run test:run`, `npm run build`) - no Node in env

## Line References Updated

All test line references in the PR description should be updated to reflect the new test file structure.
