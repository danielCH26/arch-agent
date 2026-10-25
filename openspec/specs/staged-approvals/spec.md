# Spec: staged-approvals

> Capability: `staged-approvals` · Issue: [#21](https://github.com/danielCH26/arch-agent/issues/21) · Branch: `feature/hu10-staged-approvals-v2` · Base: `development` · v2 supersedes v1 (`feature/hu10-staged-approvals`, CHANGES_REQUESTED, must NOT merge) · ADR-015 supersedes ADR-014.

## Purpose

`staged-approvals` gives the user explicit, observable, atomic control over every stage of the architecture-design flow (`requerimientos` -> `propuesta` -> `refinamiento` -> `revision` -> `final`). Each phase exposes Aprobar / Modificar / Rechazar (Aprobar / Rechazar only on `final`); no phase advances without an explicit user decision. Storage is unified on the F05 `approvals` table (extended with `project_id NOT NULL`, `previous_output JSONB`); `proposal_approvals` is a backward-compat mirror for `propuesta`. This v2 canonical REPLACES v1 (which contradicted the v1 change-folder copy at REQ-SA-5 and missed all 11 PR #78 review findings) and closes blockers REQ-SA-26..29 plus important findings REQ-SA-30..36.

## Ownership of `phase_ready` (single canonical writer per phase)

| Phase | Owner | Endpoint | Source spec |
|---|---|---|---|
| `requerimientos` | F05 | `/api/elicitation/decision` | F05 |
| `propuesta` | HU10 | `/api/projects/{id}/phase/propuesta/decision` | this spec |
| `refinamiento` | HU10 | `/api/projects/{id}/phase/refinamiento/decision` | this spec |
| `revision` | HU10 | `/api/projects/{id}/phase/revision/decision` | this spec |
| `final` | HU10 | `/api/projects/{id}/phase/final/decision` | this spec |

`/advance` MUST verify the HU10 approval record for HU10-owned phases before flipping `phase_ready=true`. See REQ-SA-36.

## Requirements

### Phase taxonomy & gate

### REQ-SA-1: Per-phase approval surface
**MUST** expose Aprobar / Modificar / Rechazar actions for the 5 phases in REQ-SA-4. **Rationale**: uniform affordance across the flow keeps the user model simple.

#### Scenario: SCN-SA-1.1 Approve advances pending phase
- GIVEN `current_phase="propuesta"`, `phase_ready=false`
- WHEN user clicks Aprobar
- THEN response is 200 AND `phase_ready=true` AND the next pending phase is `refinamiento`.

#### Scenario: SCN-SA-1.2 Rechazar on `final` keeps the project in `final`
- GIVEN `current_phase="final"`, `phase_ready=false`
- WHEN user clicks Rechazar
- THEN `phase_ready` remains `false` AND `current_phase` remains `final`.

### REQ-SA-2: No auto-advance (chat + LLM)
**MUST NOT** mutate `projects.current_phase` based on chat content OR LLM completion. Advancement requires an explicit user approve decision recorded against `(project_id, phase)` OR `/advance` gated by `phase_ready=true` (REQ-SA-36). **Rationale**: covers the v1 REQ-SA-12 agent-never-auto-advances semantic and the v1 REQ-SA-2 chat-no-auto-advance semantic in one place.

#### Scenario: SCN-SA-2.1 Chat message does not advance phase
- GIVEN `current_phase="propuesta"`, `phase_ready=true`
- WHEN user sends a chat message
- THEN chat response streams normally AND `current_phase` remains `propuesta`.

#### Scenario: SCN-SA-2.2 LLM completion does not advance phase
- GIVEN `current_phase="propuesta"`, `phase_ready=false`
- WHEN the LLM finishes streaming a proposal
- THEN `current_phase` remains `propuesta` UNTIL user POSTs `action="approve"`.

### REQ-SA-3: Decision persistence
**MUST** persist every approval decision with `project_id`, `session_id`, `phase`, `decision`, `created_at`, optional `feedback`, optional `payload`, and `previous_output` (canonical field; alias `current_output` for `revision` only, see REQ-SA-33).

#### Scenario: SCN-SA-3.1 Required fields populated
- GIVEN a decision POST with `action="approve"`
- WHEN the row is written
- THEN `approvals.project_id`, `approvals.phase`, `approvals.decision="approve"`, `approvals.created_at`, `approvals.previous_output` SHALL be populated.

### REQ-SA-4: Phase list is exactly 5
**MUST** define `AVAILABLE_PHASES = ["requerimientos", "propuesta", "refinamiento", "revision", "final"]`.

#### Scenario: SCN-SA-4.1
- GIVEN the API is started
- WHEN `GET /api/projects/{id}/phases` is called
- THEN `current_phase` SHALL be one of the 5 listed values.

### REQ-SA-5: Linear transitions
**MUST** follow the linear order in REQ-SA-4. Skipping or branching **MUST** be rejected by `record_decision` (see REQ-SA-28) and by `/advance` (see REQ-SA-36). **Rationale**: this REQ reconciles v1 canonical REQ-SA-5 ("Linear transitions") with the v2 endpoint contract; the v1 change-folder's contradictory "Phase-order agnostic" wording is rejected.

#### Scenario: SCN-SA-5.1 Skipping is rejected with 409
- GIVEN `current_phase="requerimientos"`
- WHEN decision endpoint is called with `phase="refinamiento"`
- THEN response SHALL be 409 with `{detail: {current_phase: "requerimientos"}}` (REQ-SA-28).

### Modify semantics

### REQ-SA-6: Modify re-prompts LLM for prose phases
**MUST** re-prompt the LLM with the user's `feedback` for `requerimientos` / `propuesta` / `refinamiento` AND preserve the prior output in `approvals.previous_output`.

#### Scenario: SCN-SA-6.1 Modify on `refinamiento` preserves prior Mermaid
- GIVEN `refinamiento` with prior Mermaid X
- WHEN user clicks Modificar with `feedback="use event-driven"`
- THEN `previous_output = X` AND a new Mermaid is generated.

### REQ-SA-7: Modify allows direct UI edit for `revision`
**MUST** allow direct UI editing of `{patron_elegido, ventajas, desventajas}` for `revision`. The edit **MUST** be applied via the modify handler (not merely persisted to `approvals`); see REQ-SA-33.

#### Scenario: SCN-SA-7.1
- GIVEN `revision` with current trade-offs `{patron_elegido: "Event Sourcing"}`
- WHEN user edits to `"CQRS"` and confirms
- THEN the structured form commits AND `approvals.current_output` is updated AND the underlying trade-off record is updated.

### REQ-SA-8: `final` exposes only Aprobar / Rechazar
**MUST NOT** render Modify on `final`.

#### Scenario: SCN-SA-8.1
- GIVEN `current_phase="final"`
- WHEN `<PhaseActions>` renders
- THEN DOM SHALL contain Aprobar + Rechazar only (no Modificar).

### Concurrency

### REQ-SA-9: Conflicting decisions return 409
**MUST** return HTTP 409 with body `{detail: {current_decision, decided_at, current_phase}}` (FastAPI wraps in `detail`; see REQ-SA-29) when a conflicting decision exists for `(project_id, phase)` outside the idempotency window (REQ-SA-30).

#### Scenario: SCN-SA-9.1 Double-click race returns 409 on second
- GIVEN a project in `requerimientos`
- WHEN two POSTs of `action="approve"` arrive within 50 ms
- THEN first returns 200 AND second returns 409 with `{detail: {current_decision: "approve", decided_at: <ts>, current_phase: "requerimientos"}}`.

### REQ-SA-10: Idempotency window
**SHOULD** allow identical retries within 60s (governed by REQ-SA-30). Different-action retries within the window are NOT blocked (REQ-SA-30 supercedes v1's blanket-window rule that broke modify->approve flows).

#### Scenario: SCN-SA-10.1 Identical retry within 60s returns 200
- GIVEN an `approve` recorded 30s ago
- WHEN identical POST (same payload_hash) arrives
- THEN response SHALL be 200 with `{idempotent: true, decision_id: <original>}`.

### Frontend mount signals

### REQ-SA-11: Chat emits `event: phase_locked` AND ChatWindow consumes it
**MUST** emit `event: phase_locked` as the FIRST SSE event when `phase_ready=true` AND `ChatWindow` **MUST** mount `<PhaseActions>` on receiving that event.

#### Scenario: SCN-SA-11.1
- GIVEN `current_phase="propuesta"`, `phase_ready=true`
- WHEN user POSTs to `/api/chat`
- THEN SSE first event is `event: phase_locked` with `data: {"phase": "propuesta", "phase_ready": true}` AND the stream continues with normal chat content.

#### Scenario: SCN-SA-11.2 No `phase_locked` when not locked
- GIVEN `phase_ready=false`
- WHEN user POSTs to `/api/chat`
- THEN SSE stream SHALL NOT contain `event: phase_locked`.

### REQ-SA-12: `GET /api/projects/{id}/phases` includes `pending_decision`
**MUST** return `{current_phase, phase_ready, pending_decision: {phase, since} | null}` so `ChatWindow` mounts `<PhaseActions>` from a polling path (defense in depth with REQ-SA-11 SSE). **Rationale**: closes PR #78 blocker #1 (SSE-only mount never triggered in production).

#### Scenario: SCN-SA-12.1
- GIVEN `current_phase="refinamiento"` with no recorded decision
- WHEN `GET /api/projects/{id}/phases` is called
- THEN response includes `pending_decision = {phase: "refinamiento", since: <ts>}`.

#### Scenario: SCN-SA-12.2 Mount from fetch even when SSE missed
- GIVEN `phase_ready=true` AND SSE disconnected
- WHEN `ChatWindow` mounts and fetches `/phases`
- THEN `<PhaseActions>` SHALL be present in DOM (mount from fetch path).

### Decision transport

### REQ-SA-13: Decisions via dedicated POST endpoint
**MUST** submit decisions via `POST /api/projects/{id}/phase/{phase}/decision`. **MUST NOT** send via SSE.

#### Scenario: SCN-SA-13.1 Valid POST returns 200 + decision_id
- GIVEN a project in `propuesta`
- WHEN user POSTs `{action: "approve"}` to `/api/projects/{id}/phase/propuesta/decision`
- THEN response is 200 with `{decision_id, phase, next_phase, decided_at}`.

#### Scenario: SCN-SA-13.2 Invalid body returns 422
- GIVEN a project in `requerimientos`
- WHEN user POSTs `{action: "invalid"}`
- THEN response SHALL be 422.

### REQ-SA-14: Decision body schema
**MUST** match `{action: "approve"|"modify"|"reject", feedback?: string, payload?: object, idempotency_key?: string}`.

#### Scenario: SCN-SA-14.1 Missing feedback on modify returns 400
- GIVEN `action="modify"`
- WHEN body omits `feedback`
- THEN response SHALL be 400.

### REQ-SA-15: Decision response schema
200 response **MUST** be `{decision_id, phase, next_phase, decided_at, idempotent?: boolean}`. 409 response **MUST** be `{detail: {current_decision, decided_at, current_phase}}` (REQ-SA-29).

#### Scenario: SCN-SA-15.1 `final` approve returns `next_phase=null`
- GIVEN `current_phase="final"`, `action="approve"`
- WHEN response is rendered
- THEN `next_phase=null` AND the project SHALL be archived.

### Persistence

### REQ-SA-16: `approvals.previous_output` column
Migration `0015_add_previous_output_to_approvals.sql` **MUST** add `previous_output JSONB NOT NULL DEFAULT '{}'::jsonb` AND widen the `decision` CHECK to `('approve','modify','reject')`.

#### Scenario: SCN-SA-16.1 Migration is idempotent
- GIVEN migration 0015 already applied
- WHEN `scripts/setup-local.sh` reruns `run_migrations.py`
- THEN script SHALL NOT raise AND table counts SHALL be unchanged.

### REQ-SA-17: `propuesta` dual-write with `project_id`
**MUST** write to BOTH `approvals` AND `proposal_approvals` in a single DB transaction. The `proposal_approvals` mirror row **MUST** carry the same `project_id` as the canonical `approvals` row. **Rationale**: closes PR #78 cross-project contamination.

#### Scenario: SCN-SA-17.1 propuesta decision writes both tables with matching project_id
- GIVEN a project in `propuesta`
- WHEN user POSTs `action="approve"`
- THEN one row in `approvals` for `(project_id, propuesta)` AND one row in `proposal_approvals` with matching `project_id` for the same `proposal_id`.

### REQ-SA-18: Read-path index on `project_id`
Migration `0017_add_project_id_to_approvals.sql` **MUST** create index `approvals(project_id, phase, created_at DESC)`. **Rationale**: replaces the v1 session_id index; sessions.user_id is unique so session-scoped reads cross-contaminated across the same user's projects.

#### Scenario: SCN-SA-18.1 Index used for per-project read
- GIVEN the index exists
- WHEN read query `SELECT * FROM approvals WHERE project_id=? AND phase=? ORDER BY created_at DESC LIMIT 1` runs
- THEN planner SHALL use the index.

### Frontend

### REQ-SA-19: `<PhaseActions>` mount condition
**MUST** mount in `ChatWindow` whenever a pending decision exists for the current phase (driven by REQ-SA-11 SSE OR REQ-SA-12 fetch).

#### Scenario: SCN-SA-19.1
- GIVEN `approvalsStore.pendingPhase="refinamiento"`
- WHEN `<ChatWindow>` renders
- THEN `<PhaseActions>` SHALL be present in DOM.

#### Scenario: SCN-SA-19.2
- GIVEN `approvalsStore.pendingPhase=null`
- WHEN `<ChatWindow>` renders
- THEN `<PhaseActions>` SHALL NOT be in DOM.

### REQ-SA-20: Button affordances
Aprobar / Rechazar **MUST** be one-click. Modify **MUST** open `<PhaseFeedbackComposer>` modal or inline form. Reject **MUST** open inline `<RejectDialog>` (REQ-SA-32).

#### Scenario: SCN-SA-20.1
- GIVEN `<PhaseActions>` rendered for `propuesta`
- WHEN user clicks Aprobar
- THEN POST fires immediately with `feedback` absent.

### REQ-SA-21: Cross-phase decision state
`approvalsStore` **MUST** hold cross-phase decision state via Zustand.

#### Scenario: SCN-SA-21.1
- GIVEN `<PhaseActions>` rendered for `refinamiento`
- WHEN user clicks Aprobar and 200 returns
- THEN `approvalsStore.recordApproved("refinamiento", decisionId)` SHALL be called.

### REQ-SA-22: Typed REST client
`frontend/src/api/approvals.ts` **MUST** expose `decide(projectId, phase, body)` and `list(projectId)`. `frontend/src/api/phases.ts` **MUST** expose `getPhases(projectId)`.

#### Scenario: SCN-SA-22.1
- GIVEN `decide(projectId, "propuesta", {action: "approve"})` call
- WHEN client serializes
- THEN HTTP body is `{"action": "approve"}` AND URL ends in `/phase/propuesta/decision`.

### Retire

### REQ-SA-23: `mark-ready` endpoint removed
`POST /api/projects/{id}/mark-ready` **MUST NOT** be exposed.

#### Scenario: SCN-SA-23.1
- WHEN any client POSTs to `/api/projects/{id}/mark-ready`
- THEN response SHALL be 404.

### REQ-SA-24: `markReady` frontend export removed
Frontend `markReady` client export **MUST** be deleted from `frontend/src/api/projects.ts`.

#### Scenario: SCN-SA-24.1
- GIVEN build complete
- WHEN grep runs for `markReady` in `frontend/src/`
- THEN 0 hits.

### Provenance

### REQ-SA-25: v2 spec replaces v1; ADR-015 supersedes ADR-014
**MUST** treat this v2 spec as canonical for `staged-approvals`; v1 `openspec/specs/staged-approvals/spec.md` is superseded. ADR-015 (`docs/adr/015-hu10-phase-gate-v2.md`) records the v2 contract.

#### Scenario: SCN-SA-25.1
- GIVEN PR #78 is open with CHANGES_REQUESTED
- WHEN v2 spec is merged
- THEN `openspec/specs/staged-approvals/spec.md` SHALL be v2 content AND `docs/adr/015-hu10-phase-gate-v2.md` SHALL exist.

### Blockers closed (REQ-SA-26..29)

### REQ-SA-26: Frontend MUST surface `pending_decision` via `/phases` OR `event: phase_locked`
**MUST** surface pending decisions through BOTH channels (REQ-SA-11 SSE + REQ-SA-12 fetch) so `<PhaseActions>` mounts in production even when SSE is missed. **Rationale**: closes PR #78 blocker #1 (production never mounted PhaseActions because SSE was the only signal).

#### Scenario: SCN-SA-26.1 Mount from fetch when SSE missed
- GIVEN a project in `propuesta` with `phase_ready=false` AND a pending decision recorded
- WHEN `ChatWindow` mounts AND SSE is disconnected
- THEN `GET /api/projects/{id}/phases` returns `pending_decision` AND `<PhaseActions>` SHALL mount from the fetch path alone.

#### Scenario: SCN-SA-26.2 Mount from SSE
- GIVEN `phase_ready=true` AND user POSTs to `/api/chat`
- WHEN SSE stream begins
- THEN `ChatWindow` SHALL mount `<PhaseActions>` on receiving `event: phase_locked`.

### REQ-SA-27: `approvals.project_id NOT NULL` + per-project filter
**MUST** add `project_id BIGINT NOT NULL` column to `approvals` (FK to `projects(id) ON DELETE CASCADE`), backfill from `sessions.project_id`, create index `(project_id, phase, created_at)`. `record_decision` **MUST** filter by `(project_id, phase)`. **Rationale**: closes PR #78 blocker #2 (decisions cross-contaminated across projects of same user; sessions.user_id is unique).

#### Scenario: SCN-SA-27.1 No cross-project contamination
- GIVEN a user with 2 projects A and B, both in `propuesta`
- WHEN user approves project A
- THEN exactly one row exists in `approvals` for `(project_id=A, phase="propuesta")` AND zero rows for `(project_id=B, ...)`.

#### Scenario: SCN-SA-27.2 Migration backfill is idempotent
- GIVEN migration 0017 already applied
- WHEN `setup-local.sh` reruns `run_migrations.py`
- THEN script SHALL NOT raise AND `approvals.project_id` SHALL be NOT NULL.

### REQ-SA-28: `record_decision` MUST reject with 409 when `phase != project.current_phase`
**MUST** return HTTP 409 with body `{detail: {current_decision, decided_at, current_phase}}` when `phase != project.current_phase` (no skipping). **Rationale**: closes PR #78 blocker #3 (v1 validated `phase in AVAILABLE_PHASES` but not `phase == current_phase`).

#### Scenario: SCN-SA-28.1 Skipping fase is rejected
- GIVEN `current_phase="requerimientos"`
- WHEN decision endpoint called with `phase="refinamiento"`
- THEN response SHALL be 409 with `{detail: {current_phase: "requerimientos"}}`.

### REQ-SA-29: Frontend reads `err.data.detail.*` and integration test covers real HTTP shape
**MUST** read `err.data.detail.{current_decision, decided_at, current_phase}` in `frontend/src/stores/approvals.ts` (FastAPI wraps in `detail`). **MUST** ship an integration test asserting the real HTTP error body shape end-to-end. **Rationale**: closes PR #78 blocker #4 (v1 read `err.data.current_decision` instead of `err.data.detail.current_decision`).

#### Scenario: SCN-SA-29.1 Typed read from `detail`
- GIVEN backend returns 409 with `{detail: {current_decision: "approve", decided_at: "2026-09-27T22:00:00Z", current_phase: "propuesta"}}`
- WHEN `approvalsStore.handleDecisionError` runs
- THEN store SHALL surface `currentDecision`, `currentPhase`, and a typed `ApiConflictError` (REQ-SA-34).

#### Scenario: SCN-SA-29.2 Integration test asserts real shape
- GIVEN the integration test boots FastAPI against a real DB
- WHEN two simultaneous approves are POSTed
- THEN test SHALL assert second response body matches `{detail: {current_decision, decided_at, current_phase}}` exactly.

### Important findings closed (REQ-SA-30..36)

### REQ-SA-30: Idempotency key = `(action, payload_hash, feedback)` per request
**MUST** derive idempotency from `(action, canonical payload, normalized feedback)` of the request body, where feedback is normalized as `(feedback or "").strip()` (absent feedback counts as the empty string). Identical retries within 60s **MUST** return 200 with `idempotent: true`. Two submissions with the same action and payload but DIFFERENT feedback are NOT identical and **MUST** be accepted as new decisions (new `decision_id`, feedback persisted). Different-action retries within window **MUST** be allowed (60s window applies only to identical retries). **Rationale**: closes PR #78 important finding (60s window blocked normal modify->approve flows); amended after audit — the real frontend sends `feedback` and never `payload`, so a key of `(action, payload)` alone collapsed corrected feedback into the original decision.

#### Scenario: SCN-SA-30.1 Identical retry returns idempotent 200
- GIVEN an `approve` recorded 30s ago
- WHEN identical POST (same payload bytes -> same payload_hash) arrives
- THEN response SHALL be 200 with `{idempotent: true, decision_id: <original>}`.

#### Scenario: SCN-SA-30.2 Different-action retry is allowed within window
- GIVEN `approve` recorded 30s ago
- WHEN `modify` POST arrives within 60s
- THEN response SHALL be 200 (different action; window does NOT block).

### REQ-SA-31: `SELECT ... FOR UPDATE` on project row before INSERT + Postgres concurrency test
**MUST** acquire `SELECT ... FOR UPDATE` on the `projects` row before INSERT into `approvals`. **MUST** ship a Postgres-backed concurrency test (NOT SQLite) that fires 2 simultaneous approves and asserts one 200 + one 409. **Rationale**: closes PR #78 important finding (no row lock -> race on double-click).

#### Scenario: SCN-SA-31.1
- GIVEN a project in `requerimientos`
- WHEN two POSTs of `action="approve"` arrive within 5ms (Postgres test)
- THEN exactly one SHALL return 200 AND the other SHALL return 409.

### REQ-SA-32: Inline `<RejectDialog>` replaces `window.prompt`
**MUST** render inline `<RejectDialog>` (React component) for Reject confirmation. **`window.prompt` is FORBIDDEN** in the React tree for the Reject flow. Cancel **MUST** abort (no reject recorded). **Rationale**: closes PR #78 important finding (`window.prompt` returning `null` was treated as reject).

#### Scenario: SCN-SA-32.1 Inline dialog renders
- GIVEN `<PhaseActions>` rendered for `propuesta`
- WHEN user clicks Rechazar
- THEN `<RejectDialog>` SHALL render inline (NOT `window.prompt`).

#### Scenario: SCN-SA-32.2 Cancel aborts
- GIVEN `<RejectDialog>` open
- WHEN user clicks Cancel
- THEN dialog closes AND zero rows in `approvals` SHALL be added.

### REQ-SA-33: `previous_output` semantics per phase; `revision` field renamed `current_output`
**MUST** document `previous_output` semantics per phase: for `requerimientos`/`propuesta`/`refinamiento` it carries prior LLM output; for `revision` it carries `{}` because the user provides direct edits. For `revision` the canonical field **MUST** be `current_output`; `previous_output` is retained as a one-release deprecation alias. Revision direct edit **MUST** be applied via the modify handler (NOT just persisted to `approvals`). **Rationale**: closes PR #78 important finding (`previous_output` was `{}` for most phases and in `revision` stored new payload not previous).

#### Scenario: SCN-SA-33.1 Revision edit applied via modify handler
- GIVEN `revision` with current trade-offs
- WHEN user edits `{patron_elegido}` and confirms Modify
- THEN `approvals.current_output` SHALL be the new payload AND the trade-off record SHALL be updated by the modify handler.

#### Scenario: SCN-SA-33.2 Backward-compat alias for v1 clients
- GIVEN a v1-era row with `previous_output` in `revision`
- WHEN `frontend/src/api/phases.ts` returns the decision
- THEN response SHALL map `previous_output` -> `current_output` for one release.

### REQ-SA-34: Typed `ApiConflictError` + structured body; never `str(exc)` to clients
**MUST** define a typed `ApiConflictError` class with `{current_decision, decided_at, current_phase}`. The backend **MUST NEVER** return `str(exc)` to clients in error paths. **Rationale**: closes PR #78 important finding (ad-hoc error serialization leaked Python repr to clients).

#### Scenario: SCN-SA-34.1 Typed error body
- GIVEN a 409 conflict
- WHEN FastAPI serializes the error
- THEN body SHALL be `{detail: {current_decision, decided_at, current_phase}}` matching `ApiConflictError` shape.

#### Scenario: SCN-SA-34.2 No `str(exc)` in error paths
- GIVEN `app/api/` source tree
- WHEN `grep -rn "str(exc)" app/api/` runs
- THEN 0 hits.

### REQ-SA-35: `get_latest_decision` removed
**MUST NOT** expose `get_latest_decision` (unused). **Rationale**: closes PR #78 important finding (unused helper left in surface area).

#### Scenario: SCN-SA-35.1
- GIVEN the API is started
- WHEN grep runs for `get_latest_decision` in `app/api/` and `app/core/`
- THEN 0 hits (or only in an explicitly excluded module).

### REQ-SA-36: Single canonical owner of `phase_ready`
**MUST** enforce a single canonical owner per phase per the Ownership table at the top of this spec. `/advance` **MUST** check the HU10 approval record for HU10-owned phases before flipping `phase_ready`. F05 retains sole write to the `requerimientos` approval row. **Rationale**: closes PR #78 important finding (F05 / F08 / HU10 all wrote `phase_ready` independently).

#### Scenario: SCN-SA-36.1 `/advance` blocked without HU10 approval
- GIVEN `current_phase="refinamiento"` AND no HU10 approval row
- WHEN `/advance` is called
- THEN response SHALL be 409 (no approval record found for HU10-owned phase).

#### Scenario: SCN-SA-36.2 F05 sole writer for `requerimientos`
- GIVEN F05 approves `requerimientos`
- WHEN HU10 owner check runs
- THEN F05's `approvals` row for `requerimientos` SHALL be canonical AND HU10 SHALL NOT overwrite it.

## Data model

| Table | New / changed columns | Existing columns | FK |
|---|---|---|---|
| `approvals` | `project_id BIGINT NOT NULL FK projects(id) ON DELETE CASCADE` (migration 0017); `previous_output JSONB NOT NULL DEFAULT '{}'` (migration 0015); alias `current_output` for `revision` rows (one release) | `id`, `session_id`, `phase`, `decision`, `feedback`, `payload`, `created_at` | `sessions(id)` CASCADE, `projects(id)` CASCADE |
| `proposal_approvals` | mirror rows carry `project_id` matching canonical `approvals.project_id` | `id`, `proposal_id`, `decision`, `previous_output`, `created_at` | `proposals(id)` CASCADE, `projects(id)` |

Indexes: `approvals(project_id, phase, created_at DESC)` (migration 0017, replaces v1 session-scoped index). Migration files: `0015_add_previous_output_to_approvals.sql`, `0017_add_project_id_to_approvals.sql`. Both idempotent (`ADD COLUMN IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`).

## Out of scope

- Multi-user concurrent approval / RBAC.
- Slack / email notifications, audit log UI, decision history view.
- Deprecation of `proposal_approvals` (dual-write maintained for F08 backward compat).
- F05 / F08 endpoint replacement (only de-conflict `phase_ready` writes per REQ-SA-36).
- LLM-side prompt changes that auto-detect phase completion.
- Real LLM E2E as a merge block (manual smoke recommended; CI smoke deferred).

## Risks

- Backfill orphans (rows without resolvable `project_id`): backfill from `sessions.project_id`; NULL left for manual triage + logged warning; not a blocker.
- F05/F08 dual-write to `phase_ready` still races via `/advance`: mitigated by REQ-SA-36 single-owner table.
- `str(exc)` regression: mitigated by REQ-SA-34 audit + CI grep gate.

## References

- Proposal: `openspec/changes/hu10-staged-approvals-v2/proposal.md` (Engram id 109).
- PR #78 review: Engram id 108 (11 findings closed by REQ-SA-26..36).
- v1 spec (SUPERSEDED): `openspec/specs/staged-approvals/spec.md` prior content.
- v1 proposal (SUPERSEDED): `openspec/changes/hu10-staged-approvals/proposal.md`.
- Per-domain delta: `openspec/changes/hu10-staged-approvals-v2/specs/proposal-approval/spec.md`.
- Issue [#21](https://github.com/danielCH26/arch-agent/issues/21).
- ADR-014 (v1, historical); ADR-015 (v2 successor) — `docs/adr/015-hu10-phase-gate-v2.md`.
