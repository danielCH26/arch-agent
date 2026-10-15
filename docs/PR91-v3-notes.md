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
- Added explicit `+00:00` suffix in ISO string serialization for JavaScript `Date()` parsing (now applied to EVERY timestamp via `_iso_utc`, see "Review round 3" below)
- Added `getProject` method to projectsStore for refresh after advance

## Test Command and Expected Results

```bash
pytest tests/core/test_phase_decisions.py tests/api/test_projects_hu10.py -v
```

Expected: all green. Test counts drift as tests are added, so this note no
longer pins a number; the PR description carries the counts for the current
head commit.

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
| `app/core/phase_decisions.py` | Inverted pending_decision semantics, removed DecisionConflict, fixed datetime.utcnow(); round 3: shared `_last_decision`, null timestamps, key normalisation |
| `app/api/projects.py` | Added FOR UPDATE, fixed per_phase.status, added previous_output; round 3: detached-session fix, `_iso_utc`, no `str(e)` |
| `app/api/proposals.py` | Routed through record_decision; round 3: typed errors, scoped duplicate guard |
| `app/api/phase_errors.py` | New (round 3): single `PhaseDecisionError` -> HTTP mapper |
| `frontend/src/components/PhaseActions/PhaseActions.tsx` | Added Avanzar button; round 3: `hideDecision`, refresh + error after advance |
| `frontend/src/stores/projectsStore.ts` | Added getProject method |
| `frontend/src/stores/proposalsStore.ts` | Round 3: re-sync approvals + project after `decide` |
| `frontend/src/api/client.ts` | Round 3: readable message for typed `detail` |
| `scripts/walk_hu10_e2e.py` | Round 3: 422 for modify on `final`; approve `propuesta` through the UI path |
| `tests/conftest.py` | Fixed DATABASE_URL setdefault |
| `tests/core/test_phase_decisions.py` | Updated tests for new semantics |
| `tests/api/test_projects_hu10.py` | Updated tests for new semantics |

## Review round 3 (Soomri 2026-10-07 + follow-up review)

Fixes on top of the rounds above. Each one has a test; the walk is the
acceptance gate for the whole flow.

| Finding | Fix | Where |
|---|---|---|
| `POST /phase/{phase}/decision` answered 500 after saving (reads `result.approval.*` after `commit()` + `close()` -> `DetachedInstanceError`) | `db.refresh()` and copy `id` / `created_at` / `next_phase` / `idempotent` while the session is open | `app/api/projects.py` |
| Walk expected 400 for modify on `final`; the endpoint answers 422 (`InvalidActionError`) | Walk aligned to 422 | `scripts/walk_hu10_e2e.py` |
| Walk read `phase_ready` from `PhaseDecisionOut`, which has no such field; walk approved `propuesta` through the generic endpoint | Walk approves via `/api/proposals/{id}/decide` (the UI path) and checks `lifecycle` + `phase_ready` from that response | `scripts/walk_hu10_e2e.py` |
| `propuesta` had two decision surfaces that disagreed (generic endpoint never touches `proposal.lifecycle`, the `engram_state` snapshot or reject->revert) | `<PhaseActions hideDecision>` on `propuesta` (only Avanzar); `proposalsStore.decide` re-syncs approvals + project | `PhaseActions.tsx`, `ChatWindow.tsx`, `proposalsStore.ts` |
| After Avanzar the new phase showed no decision buttons | `refresh()` after advance + re-fetch on phase change; advance errors shown in the UI | `PhaseActions.tsx`, `ChatWindow.tsx` |
| `str(exc)` still leaked from `decide_proposal`, `decide_project_proposal`, `advance_phase`; `PhaseMismatchError` there was a 500 | One mapper (`app/api/phase_errors.py`) for typed 409/422 + generic `{"error": "internal_error"}` for the 500 fallback; the client turns typed `detail` into a readable message | `phase_errors.py`, `projects.py`, `proposals.py`, `api/client.ts` |
| `/advance` gate used "any approved row", `get_pending_decision` used "last decision" | Both go through `_last_decision` | `app/core/phase_decisions.py` |
| `last_decided_at` lacked the `+00:00` that `since` had; `since` was `now()` with no decisions | Single `_iso_utc` helper; `since` / `last_decided_at` are `None` when no decision is on file | `projects.py`, `phase_decisions.py` |
| `idempotency_key` longer than 32 chars -> `DataError` (`payload_hash` is `String(32)`) | Keys over 32 chars are digested (SHA-256, 32 hex); shorter keys are stored verbatim | `phase_decisions.py` |
| Duplicate-decision guard (`InteractionLog`) matched the previous proposal's row: reject -> revert -> new proposal -> reject gave a bogus 409 | Guard only counts rows logged at/after the current proposal was created (no `proposal_id` column exists) | `proposals.py` |

### Known limitations (not fixed here)

- `POST /phase/propuesta/decision` is still reachable through the API and still
  does not move `proposal.lifecycle`. The UI no longer offers it on `propuesta`;
  closing it at the API level (reject it for `propuesta`, or delegate to the
  proposals logic) needs a product decision.
- `since` / `last_decided_at` / `decided_at` assume the database session runs
  in UTC (`approvals.created_at` is `TIMESTAMP` without time zone). True for
  the docker-compose Postgres; a `TIMESTAMPTZ` migration would remove the
  assumption.
- `ProposalApproval` / `InteractionLog` rows in `decide_proposal` are not
  deduplicated by `record_decision`'s idempotency window; they are protected
  by the lifecycle check and the guard above (documented in the code).
- Other endpoints still return `str(e)` (`elicitation.py`, `chat.py`,
  `llm_config.py`, `documents.py`, `auth.py`). Out of scope for HU10.

## Deferred to CI

- Postgres-backed tests (`test_phase_decisions_concurrency.py`, `tests/models/test_approval.py`) need a runner with a live Postgres (re-review B2).
- The 5-phase walk with a real LLM (`scripts/walk_hu10_e2e.py`) has not been executed yet; it needs credentials.
- Re-run `pytest`, `npm run build` and `npm run test:run` on the head commit of this PR.
