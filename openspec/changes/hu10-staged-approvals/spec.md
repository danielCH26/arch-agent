# Delta for `staged-approvals` — Change `hu10-staged-approvals`

> Change folder: `openspec/changes/hu10-staged-approvals/`
> Canonical capability: `openspec/specs/staged-approvals/spec.md` (NEW)
> Per-domain deltas: `openspec/changes/hu10-staged-approvals/specs/proposal-approval/spec.md`
> Artifact store: hybrid (this file + Engram topic `sdd/hu10-staged-approvals/spec`)

This change introduces the `staged-approvals` capability (NEW canonical spec) and adds a per-phase decision endpoint plus a chat-side `phase_locked` SSE signal to satisfy issue #21 ("Aprobar o rechazar cada etapa del flujo"). All requirements below are ADDED — there is no pre-existing capability being modified directly. The `proposal-approval` capability is touched as a downstream consumer (dual-write) and has its own per-domain delta at `specs/proposal-approval/spec.md`.

## ADDED Requirements

### REQ-SA-1: Per-phase approval surface
The system SHALL expose Aprobar / Modificar / Rechazar actions for each of the 5 phases listed in REQ-SA-4.

#### Scenario: SCN-SA-1.1: Approve action advances phase
- GIVEN a project in `propuesta` with `phase_ready=false`
- WHEN user clicks Aprobar
- THEN the system SHALL POST `action="approve"`; `phase_ready` SHALL become `true`; the next pending phase SHALL be `refinamiento`.

#### Scenario: SCN-SA-1.2: Rechazar on `final` keeps the project in `final`
- GIVEN a project in `final` with `phase_ready=false`
- WHEN user clicks Rechazar
- THEN `phase_ready` SHALL remain `false` AND `current_phase` SHALL remain `final`.

### REQ-SA-2: No auto-advance
The system SHALL NOT advance a phase to the next without an explicit user approval decision recorded against `(project_id, phase)`.

#### Scenario: SCN-SA-2.1: Chat message does not advance phase
- GIVEN `current_phase="propuesta"`, `phase_ready=true`
- WHEN user sends a chat message
- THEN the chat response streams normally AND `current_phase` SHALL remain `propuesta`.

### REQ-SA-3: Decision persistence
The system SHALL persist every approval decision with `session_id`, `phase`, `decision`, `created_at`, optional `feedback`, and `previous_output`.

#### Scenario: SCN-SA-3.1: Decision row contains required fields
- GIVEN a decision POST with `action="approve"`
- WHEN the row is written
- THEN `approvals.session_id`, `approvals.phase`, `approvals.decision="approve"`, `approvals.created_at`, `approvals.previous_output` SHALL be populated.

### REQ-SA-4: Phase list is exactly 5
`AVAILABLE_PHASES` SHALL equal `["requerimientos", "propuesta", "refinamiento", "revision", "final"]`.

#### Scenario: SCN-SA-4.1: Phase list has 5 entries
- GIVEN the API is started
- WHEN `GET /api/projects/{id}/phase` is called
- THEN `current_phase` SHALL be one of the 5 listed values.

### REQ-SA-5: Phase-order agnostic decisions
The decision endpoint SHALL accept a decision for any phase in `AVAILABLE_PHASES` (REQ-SA-4), regardless of the project's `current_phase`. Phase ordering is intentionally NOT enforced at this endpoint; the endpoint SHALL validate only that `phase ∈ AVAILABLE_PHASES`, `action ∈ {approve, modify, reject}`, and (for `action="modify"`) that `feedback` is non-empty. Linear phase progression is guarded separately by the `/advance` gate (requires `phase_ready=true` and emits `event: phase_locked` via SSE), and concurrency is handled by the 60s idempotency window (REQ-SA-10) + 409 on conflicting actions (REQ-SA-9).

Rationale: allowing decisions on any phase supports (a) attaching feedback (`action="modify"`) to a previously approved phase after the project has advanced (e.g. refining an earlier artefact), and (b) matches the F08 `decide_proposal` behavior, which accepts decisions on any past proposal without order enforcement.

#### Scenario: SCN-SA-5.1: Skipping is accepted (no 400 on phase mismatch)
- GIVEN `current_phase="requerimientos"`
- WHEN the decision endpoint is called with `phase="refinamiento"` and a valid body
- THEN the response SHALL be 200 (or 409 if a conflicting decision was recorded in the last 60s per REQ-SA-9) and the decision SHALL be persisted against `phase="refinamiento"`.

#### Scenario: SCN-SA-5.2: Decision on a past phase is accepted
- GIVEN `current_phase="refinamiento"` and `requerimientos` already approved
- WHEN the decision endpoint is called with `phase="requerimientos"` and `action="modify"`
- THEN the response SHALL be 200 and the new decision SHALL be persisted against `requerimientos` (the prior decision remains in history).

### REQ-SA-6: Modify re-prompts LLM for prose phases
For `requerimientos`, `propuesta`, `refinamiento`, Modify SHALL re-prompt the LLM with the user's `feedback` and SHALL preserve the prior output in `approvals.previous_output`.

#### Scenario: SCN-SA-6.1: Modify on `refinamiento` preserves prior Mermaid
- GIVEN `refinamiento` with prior Mermaid source X
- WHEN user clicks Modificar with `feedback="use event-driven"`
- THEN the system SHALL record `previous_output = X` AND re-prompt the LLM for a new Mermaid.

### REQ-SA-7: Modify allows direct UI edit for `revision`
For `revision`, Modify SHALL allow direct UI editing of `{patron_elegido, ventajas, desventajas}` and SHALL preserve the prior output.

#### Scenario: SCN-SA-7.1: Modify on `revision` opens structured form
- GIVEN `revision` with current trade-offs `{patron_elegido: "Event Sourcing", ventajas: ["…"], desventajas: ["…"]}`
- WHEN user clicks Modificar
- THEN the UI SHALL open a form pre-filled with `patron_elegido`, `ventajas`, and `desventajas`.

### REQ-SA-8: `final` exposes only Aprobar / Rechazar
For `final`, the system SHALL expose only Aprobar / Rechazar. Modify SHALL NOT be rendered.

#### Scenario: SCN-SA-8.1: `final` phase shows two buttons only
- GIVEN `current_phase="final"`
- WHEN `<PhaseActions>` renders
- THEN the DOM SHALL contain `Aprobar` and `Rechazar` buttons AND SHALL NOT contain a `Modificar` button.

### REQ-SA-9: Conflicting decisions return 409
When two decisions arrive for the same `(project_id, phase)` tuple, the second SHALL receive HTTP 409 with body `{current_decision, decided_at}`.

#### Scenario: SCN-SA-9.1: Double-click race returns 409 on second
- GIVEN a project in `requerimientos`
- WHEN two POSTs of `action="approve"` arrive within 50ms
- THEN the first SHALL return 200 AND the second SHALL return 409 with `{current_decision: "approve", decided_at: <timestamp>}`.

### REQ-SA-10: Idempotency window
If a decision for `(project_id, phase)` was recorded within the last 60s, subsequent identical decisions (same action) MAY return 200; otherwise 409.

#### Scenario: SCN-SA-10.1: Identical decision within 60s returns 200
- GIVEN an `approve` decision was recorded 30s ago
- WHEN another `approve` POST arrives
- THEN the system MAY return 200 with the original `decision_id`.

### REQ-SA-11: Chat emits `event: phase_locked` when locked
`/api/chat` SHALL emit `event: phase_locked` as the FIRST SSE event when `phase_ready=true` for the current phase AND SHALL continue streaming the chat response non-blocking.

#### Scenario: SCN-SA-11.1: Chat stream order is `phase_locked` then chat content
- GIVEN `current_phase="propuesta"`, `phase_ready=true`
- WHEN user POSTs to `/api/chat`
- THEN the SSE stream's first event SHALL be `event: phase_locked` with `data: {"phase": "propuesta", "phase_ready": true}` AND the stream SHALL continue with normal chat content.

#### Scenario: SCN-SA-11.2: No `phase_locked` when not locked
- GIVEN `phase_ready=false`
- WHEN user POSTs to `/api/chat`
- THEN the SSE stream SHALL NOT contain `event: phase_locked`.

### REQ-SA-12: Agent never auto-advances
The agent SHALL NOT mutate `projects.current_phase` based on chat content. Advancement requires an explicit approve decision.

#### Scenario: SCN-SA-12.1: LLM completion does not advance phase
- GIVEN `current_phase="propuesta"`, `phase_ready=false`
- WHEN the LLM finishes streaming a proposal
- THEN `current_phase` SHALL remain `propuesta` UNTIL a user POSTs `action="approve"`.

### REQ-SA-13: Decisions via dedicated POST endpoint
Decisions SHALL be submitted via `POST /api/projects/{id}/phase/{phase}/decision`. They SHALL NOT be sent via SSE.

#### Scenario: SCN-SA-13.1: Valid POST returns 200 + decision_id
- GIVEN a project in `propuesta`
- WHEN user POSTs `{action: "approve"}` to `/api/projects/{id}/phase/propuesta/decision`
- THEN the response SHALL be 200 with body `{decision_id, phase: "propuesta", next_phase: "refinamiento", decided_at}`.

#### Scenario: SCN-SA-13.2: Invalid body returns 422
- GIVEN a project in `requerimientos`
- WHEN user POSTs `{action: "invalid"}`
- THEN the response SHALL be 422.

### REQ-SA-14: Decision body schema
The request body SHALL match `{action: "approve"|"modify"|"reject", feedback?: string, payload?: object}`.

#### Scenario: SCN-SA-14.1: Missing feedback on modify returns 400
- GIVEN `action="modify"`
- WHEN the body omits `feedback`
- THEN the response SHALL be 400.

### REQ-SA-15: Decision response schema
200 response SHALL be `{decision_id, phase, next_phase, decided_at}`. 409 response SHALL be `{current_decision, decided_at}`.

#### Scenario: SCN-SA-15.1: `final` approve returns `next_phase=null`
- GIVEN `current_phase="final"`, `action="approve"`
- WHEN the response is rendered
- THEN `next_phase` SHALL be `null` AND the project SHALL be archived.

### REQ-SA-16: `approvals.previous_output` column
Migration `0015_add_previous_output_to_approvals.sql` SHALL add `previous_output JSONB NOT NULL DEFAULT '{}'::jsonb` to `approvals` AND SHALL widen the `decision` CHECK to `('approve','modify','reject')`.

#### Scenario: SCN-SA-16.1: Migration is idempotent
- GIVEN migration 0015 already applied
- WHEN `scripts/setup-local.sh` reruns `run_migrations.py`
- THEN the script SHALL NOT raise AND table counts SHALL be unchanged.

### REQ-SA-17: `propuesta` dual-write
For `propuesta` decisions, the system SHALL write to BOTH `approvals` AND `proposal_approvals` in a single DB transaction.

#### Scenario: SCN-SA-17.1: propuesta decision writes both tables
- GIVEN a project in `propuesta`
- WHEN user POSTs `action="approve"`
- THEN exactly one row SHALL exist in `approvals` for `(project_id, propuesta)` AND exactly one row SHALL exist in `proposal_approvals` for the same `proposal_id`.

### REQ-SA-18: Read-path index
Migration 0015 SHALL create an index on `approvals(session_id, phase, created_at DESC)` for the "last approved decision per (project, phase)" read path.

#### Scenario: SCN-SA-18.1: Index used for read query
- GIVEN the index exists
- WHEN the read query `SELECT * FROM approvals WHERE session_id=? AND phase=? ORDER BY created_at DESC LIMIT 1` runs
- THEN the planner SHALL use the index.

### REQ-SA-19: `<PhaseActions>` mount condition
`<PhaseActions>` SHALL mount in `ChatWindow` whenever a pending decision exists for the current phase.

#### Scenario: SCN-SA-19.1: Mount when pending decision exists
- GIVEN `current_phase="refinamiento"` AND `approvalsStore.pendingPhase="refinamiento"`
- WHEN `<ChatWindow>` renders
- THEN `<PhaseActions>` SHALL be present in the DOM.

#### Scenario: SCN-SA-19.2: No mount when no pending decision
- GIVEN `approvalsStore.pendingPhase=null`
- WHEN `<ChatWindow>` renders
- THEN `<PhaseActions>` SHALL NOT be in the DOM.

### REQ-SA-20: Button affordances
Aprobar / Rechazar SHALL be one-click actions. Modify SHALL open a `<PhaseFeedbackComposer>` modal or inline form.

#### Scenario: SCN-SA-20.1: Aprobar clicks post directly
- GIVEN `<PhaseActions>` rendered for `propuesta`
- WHEN user clicks Aprobar
- THEN a POST SHALL fire immediately with `feedback` absent.

### REQ-SA-21: Cross-phase decision state
`approvalsStore` SHALL hold cross-phase decision state via Zustand.

#### Scenario: SCN-SA-21.1: Store records approve
- GIVEN `<PhaseActions>` rendered for `refinamiento`
- WHEN the user clicks Aprobar and 200 returns
- THEN `approvalsStore.recordApproved("refinamiento", decisionId)` SHALL be called.

### REQ-SA-22: Typed REST client
`api/approvals.ts` SHALL expose `decide(projectId, phase, body)` and `list(projectId)` as a typed REST client.

#### Scenario: SCN-SA-22.1: Client maps body to JSON
- GIVEN a `decide(projectId, "propuesta", {action: "approve"})` call
- WHEN the client serializes the request
- THEN the HTTP body SHALL be `{"action": "approve"}` AND the URL SHALL end in `/phase/propuesta/decision`.

### REQ-SA-23: `mark-ready` endpoint removed
`POST /api/projects/{id}/mark-ready` SHALL NOT be exposed.

#### Scenario: SCN-SA-23.1: 404 on legacy endpoint
- WHEN any client POSTs to `/api/projects/{id}/mark-ready`
- THEN the response SHALL be 404.

### REQ-SA-24: `markReady` frontend export removed
Frontend `markReady` client export SHALL be deleted from `frontend/src/api/projects.ts`.

#### Scenario: SCN-SA-24.1: No client export remains
- GIVEN the build is complete
- WHEN grep runs for `markReady` in `frontend/src/`
- THEN it SHALL return 0 hits.

## REMOVED Requirements

None.

## RENAMED Requirements

None.

## Cross-references

- `proposal-approval` capability (`openspec/specs/proposal-approval/spec.md`) is touched by the dual-write behavior of REQ-SA-17. The per-domain delta at `openspec/changes/hu10-staged-approvals/specs/proposal-approval/spec.md` documents the consumer-side change.
- `interaction_logs.action_type` (free-string phase field in `app/models/interaction_log.py:5`) is extended to accept the 5 HU10 phases at call sites; no schema change required.
- `app/api/chat.py:58` is modified to emit `event: phase_locked` (REQ-SA-11) — orthogonal to the chat agent's content streaming.

## References

- Issue [#21](https://github.com/danielCH26/arch-agent/issues/21).
- `openspec/changes/hu10-staged-approvals/explore.md` (Engram id 80).
- `openspec/changes/hu10-staged-approvals/proposal.md` (Engram id 81).
- Canonical spec: `openspec/specs/staged-approvals/spec.md`.
- Per-domain delta: `openspec/changes/hu10-staged-approvals/specs/proposal-approval/spec.md`.