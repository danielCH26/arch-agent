# Delta for `staged-approvals` — Change `hu10-staged-approvals-v2`

> Change folder: `openspec/changes/hu10-staged-approvals-v2/`
> Canonical capability (REPLACED): `openspec/specs/staged-approvals/spec.md`
> Per-domain delta: `openspec/changes/hu10-staged-approvals-v2/specs/proposal-approval/spec.md`
> Artifact store: hybrid (this file + Engram topic `sdd/hu10-staged-approvals-v2/spec`)
> Supersedes: `openspec/changes/hu10-staged-approvals/` (PR #78, CHANGES_REQUESTED)

This delta documents the net-new requirements `hu10-staged-approvals-v2` introduces against the v1 canonical `staged-approvals` spec. v2 REPLACES the canonical in full (v1 had content drift vs its own change-folder copy at REQ-SA-5 and missed all 11 PR #78 review findings). 12 net-new requirements (REQ-SA-25..36) are added; 5 existing requirements are modified; none are removed.

## ADDED Requirements

### REQ-SA-25: v2 spec replaces v1; ADR-015 supersedes ADR-014
The system MUST treat `openspec/specs/staged-approvals/spec.md` (v2) as canonical and MUST ship `docs/adr/015-hu10-phase-gate-v2.md` recording the v2 contract. v1 canonical is superseded; PR #78 stays open with CHANGES_REQUESTED and MUST NOT merge.

#### Scenario: SCN-SA-25.1
- GIVEN PR #78 is open with CHANGES_REQUESTED
- WHEN v2 spec is merged
- THEN `openspec/specs/staged-approvals/spec.md` is v2 content AND `docs/adr/015-hu10-phase-gate-v2.md` exists.

### REQ-SA-26: Frontend MUST surface `pending_decision` via `/phases` OR `event: phase_locked`
The system MUST surface pending decisions through BOTH channels so `<PhaseActions>` mounts in production even when SSE is missed. Closes PR #78 blocker #1.

#### Scenario: SCN-SA-26.1 Mount from fetch when SSE missed
- GIVEN `current_phase="propuesta"` with `phase_ready=false` AND a pending decision recorded
- WHEN `ChatWindow` mounts AND SSE is disconnected
- THEN `GET /api/projects/{id}/phases` returns `pending_decision` AND `<PhaseActions>` mounts from the fetch path alone.

### REQ-SA-27: `approvals.project_id NOT NULL` + per-project filter
The system MUST add `project_id BIGINT NOT NULL` (FK to `projects(id) ON DELETE CASCADE`) to `approvals`, backfill from `sessions.project_id`, and create index `(project_id, phase, created_at DESC)`. `record_decision` MUST filter by `(project_id, phase)`. Closes PR #78 blocker #2.

#### Scenario: SCN-SA-27.1 No cross-project contamination
- GIVEN a user with 2 projects A and B, both in `propuesta`
- WHEN user approves project A
- THEN exactly one row exists in `approvals` for `(project_id=A, phase="propuesta")` AND zero rows for `(project_id=B, ...)`.

### REQ-SA-28: `record_decision` MUST reject with 409 when `phase != project.current_phase`
The system MUST return HTTP 409 with body `{detail: {error: "phase_mismatch", current_phase, requested_phase}}` when `phase != project.current_phase`. Closes PR #78 blocker #3.

#### Scenario: SCN-SA-28.1 Skipping fase rejected
- GIVEN `current_phase="requerimientos"`
- WHEN decision endpoint called with `phase="refinamiento"`
- THEN response is 409 with `{detail: {error: "phase_mismatch", current_phase: "requerimientos", requested_phase: "refinamiento"}}`.

### REQ-SA-29: Frontend reads `err.data.detail.*` and integration test covers real HTTP shape
The system MUST read `err.data.detail.{current_decision, decided_at, current_phase}` in `frontend/src/stores/approvals.ts` and MUST ship an integration test asserting the real HTTP error body shape end-to-end. Closes PR #78 blocker #4.

### REQ-SA-30: Idempotency key = `(action, payload_hash)` per request
The system MUST derive idempotency from `(action, payload_hash)`. Identical retries within 60s MUST return 200 with `idempotent: true`. Different-action retries within window MUST be allowed.

### REQ-SA-31: `SELECT ... FOR UPDATE` on project row before INSERT + Postgres concurrency test
The system MUST acquire `SELECT ... FOR UPDATE` on the `projects` row before INSERT into `approvals`. The system MUST ship a Postgres-backed concurrency test (NOT SQLite) that fires 2 simultaneous approves and asserts one 200 + one 409.

### REQ-SA-32: Inline `<RejectDialog>` replaces `window.prompt`
The system MUST render inline `<RejectDialog>` for Reject confirmation. `window.prompt` is FORBIDDEN in the React tree for the Reject flow. Cancel MUST abort.

### REQ-SA-33: `previous_output` semantics per phase; `revision` field renamed `current_output`
The system MUST document `previous_output` semantics per phase. For `revision` the canonical field is `current_output`; `previous_output` is retained as a one-release deprecation alias.

### REQ-SA-34: Typed `DecisionConflict` + structured body; never `str(exc)` to clients
The system MUST define typed `DecisionConflict` with `{current_decision, decided_at, current_phase, decision_id}`. The backend MUST NEVER return `str(exc)` to clients.

#### Scenario: SCN-SA-34.1 No `str(exc)` in error paths
- GIVEN `app/api/` source tree
- WHEN `grep -rn "str(exc)" app/api/projects.py` runs
- THEN no match inside the typed-error branches (only inside the final ``except Exception`` fallback, which is the contract's safety net).

### REQ-SA-35: `get_latest_decision` removed
The system MUST NOT expose `get_latest_decision`. (N/A on v2 base branch `development`; helper was v1-only and was never merged. Documented for traceability.)

### REQ-SA-36: Single canonical owner of `phase_ready`
The system MUST enforce the single-owner table (HU10 owns `propuesta`/`refinamiento`/`revision`/`final`; F05 owns `requerimientos`). `/advance` MUST check the HU10 approval record for HU10-owned phases before flipping `phase_ready`.

#### Scenario: SCN-SA-36.1 `/advance` blocked without HU10 approval
- GIVEN `current_phase="refinamiento"` AND no HU10 approval row
- WHEN `/advance` is called
- THEN response is 409 with `{detail: {error: "phase_not_approved", phase: "refinamiento"}}`.

## MODIFIED Requirements

### REQ-SA-9: Conflicting decisions return 409 (body shape updated)
The system MUST return HTTP 409 with body `{detail: {error, current_decision, decided_at, current_phase, decision_id}}` (FastAPI wraps in `detail`). **Previously**: body was `{current_decision, decided_at}` (no `detail` wrap, no `current_phase`, no `decision_id`).

### REQ-SA-11: Chat emits `event: phase_locked` AND ChatWindow consumes it (consumer requirement added)
`/api/chat` MUST emit `event: phase_locked` as the FIRST SSE event when `phase_ready=true`. `ChatWindow` MUST mount `<PhaseActions>` on receiving that event. **Previously**: SSE emission only; no consumer requirement; production never mounted PhaseActions.

### REQ-SA-12: `GET /api/projects/{id}/phases` includes `pending_decision`
The endpoint MUST return `{current_phase, phase_ready, pending_decision: {phase, since, last_decision, last_decided_at} | null}` so `ChatWindow` mounts `<PhaseActions>` from a polling path (defense-in-depth with REQ-SA-11 SSE). **Previously**: v1 REQ-SA-12 covered "Agent never auto-advances"; that semantic now lives in REQ-SA-2 (broadened).

### REQ-SA-17: `propuesta` dual-write with `project_id`
For `propuesta` decisions the system MUST write to BOTH `approvals` AND `proposal_approvals` in a single DB transaction; the `proposal_approvals` mirror row MUST carry the same `project_id` as the canonical `approvals` row. **Previously**: dual-write without `project_id` on the mirror row.

### REQ-SA-18: Read-path index on `project_id`
Migration 0018 MUST create index `approvals(project_id, phase, created_at DESC)`. **Previously**: v1's session-scoped index cross-contaminated across the same user's projects. F08 migration 0016 added `idx_approvals_project_phase`; v2 migration 0018 adds the extended `ix_approvals_project_phase_created` alongside (no destructive drop).

## REMOVED Requirements

None. The v2 canonical supersedes v1 in full; no individual v1 REQ is dropped — REQ-SA-1..24 are carried forward (with the five MODIFIED entries above) and REQ-SA-25..36 are net-new.

## RENAMED Requirements

### `approvals.previous_output` field -> `approvals.current_output` (for `revision` phase only)
**Reason**: v1 stored the new payload under `previous_output` for `revision`, which is semantically inverted. The v2 canonical field is `current_output`; `previous_output` is retained as a one-release deprecation alias. **Migration**: clients read `current_output`; legacy v1 readers mapping `previous_output` -> `current_output` is supported for one release (REQ-SA-33).

## Cross-references

- Canonical capability: `openspec/specs/staged-approvals/spec.md` (v2, REPLACED).
- Per-domain delta: `openspec/changes/hu10-staged-approvals-v2/specs/proposal-approval/spec.md`.
- Proposal: `openspec/changes/hu10-staged-approvals-v2/proposal.md` (Engram id 109).
- PR #78 review: Engram id 108 (the 11 findings closed by REQ-SA-26..36).
- ADR-015: `docs/adr/015-hu10-phase-gate-v2.md` (successor to ADR-014).
- Migration: `migrations/0018_backfill_project_id_and_extend_index.sql` (idempotent, additive; F08's 0016/0017 already shipped project_id and attachment_id).

## References

- Issue [#21](https://github.com/danielCH26/arch-agent/issues/21).
- v1 spec (SUPERSEDED): `openspec/specs/staged-approvals/spec.md` prior to v2 replacement.
- v1 proposal (SUPERSEDED): `openspec/changes/hu10-staged-approvals/proposal.md`.
- v1 change-folder spec: `openspec/changes/hu10-staged-approvals/spec.md`.
- v1 change-folder per-domain delta: `openspec/changes/hu10-staged-approvals/specs/proposal-approval/spec.md`.