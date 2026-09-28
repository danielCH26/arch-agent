# Delta for `proposal-approval` — Change `hu10-staged-approvals-v2`

> Capability being modified: `openspec/specs/proposal-approval/spec.md` (F08, unchanged).
> Change folder: `openspec/changes/hu10-staged-approvals-v2/specs/proposal-approval/spec.md`.
> Source change: `openspec/changes/hu10-staged-approvals-v2/spec.md` (REPLACES `hu10-staged-approvals`).

This delta documents the consumer relationship between HU10 v2 (`staged-approvals`) and the F08 `proposal-approval` capability. HU10 v2 owns the `propuesta` lifecycle end-to-end via the new generic `POST /api/projects/{id}/phase/propuesta/decision` endpoint, which dual-writes to `approvals` (canonical) AND `proposal_approvals` (F08 legacy mirror) in a single DB transaction, with the mirror row carrying the canonical `project_id`. F08 endpoints stay for backward compat on the legacy F08 frontend branch; their behavior is unchanged.

## ADDED Requirements

### REQ-PA-HU10-5: HU10 owns `propuesta` lifecycle (F08 backward compat preserved)
HU10 (`staged-approvals`) MUST own the `propuesta` lifecycle end-to-end via `POST /api/projects/{id}/phase/propuesta/decision`. F08 endpoints (`POST /api/proposals/{id}/decide`, `POST /api/proposals/{id}/modify`) remain exposed for backward compat on the legacy F08 frontend branch; their behavior is unchanged.

#### Scenario: SCN-PA-HU10-5.1 HU10 is canonical for `propuesta`
- GIVEN `current_phase="propuesta"`
- WHEN a client (HU10 frontend) POSTs `action="approve"` to `/api/projects/{id}/phase/propuesta/decision`
- THEN HU10 writes one row to `approvals` (canonical) AND one row to `proposal_approvals` (mirror) AND F08 readers continue to work unchanged.

### REQ-PA-HU10-6: Dual-write mirror row carries `project_id`
When the HU10 generic endpoint records a `propuesta` decision, the dual-write MUST include `project_id` in BOTH the canonical `approvals` row AND the `proposal_approvals` mirror row.

#### Scenario: SCN-PA-HU10-6.1 Mirror row carries matching project_id
- GIVEN a project in `propuesta`
- WHEN user POSTs `action="approve"` to `/api/projects/{id}/phase/propuesta/decision`
- THEN `approvals.project_id = <project_id>` AND `proposal_approvals.project_id = <project_id>` (same value).

### REQ-PA-HU10-7: Single canonical `<PhaseActions>` does not double-render alongside F08 `<ProposalActions>`
For `propuesta`, the HU10 generic `<PhaseActions>` is the canonical approval surface on the new frontend. F08 `<ProposalActions>` may coexist on the legacy F08 frontend path BUT MUST NOT render simultaneously with HU10 `<PhaseActions>` for the same project. CI verifies this.

#### Scenario: SCN-PA-HU10-7.1
- GIVEN `current_phase="propuesta"` AND HU10 `<PhaseActions>` is rendered
- WHEN the page mounts
- THEN F08 `<ProposalActions>` SHALL NOT be in the DOM for the same project (no double-render).

### REQ-PA-HU10-8: `propuesta` decisions follow v2 concurrency + idempotency rules
`propuesta` decisions via the HU10 generic endpoint MUST follow REQ-SA-9 (409 body shape with `detail.error` + `current_phase`), REQ-SA-28 (reject if `phase != current_phase`), REQ-SA-30 (`(action, payload_hash)` idempotency key), REQ-SA-31 (`SELECT FOR UPDATE` on project row, Postgres-backed concurrency test).

## MODIFIED Requirements

None. (Existing F08 REQ-3, REQ-4, REQ-8 in `openspec/specs/proposal-approval/spec.md` continue to apply to the legacy F08 path. The HU10 dual-write contract is extended, not replaced, by REQ-PA-HU10-5..8.)

## REMOVED Requirements

None.

## RENAMED Requirements

None for `proposal-approval` itself. The staged-approvals canonical renames `approvals.previous_output` -> `approvals.current_output` for `revision` only (REQ-SA-33); this does not affect the `proposal_approvals` schema.

## Cross-references

- Canonical `staged-approvals` capability (v2): `openspec/specs/staged-approvals/spec.md`.
- Source change delta: `openspec/changes/hu10-staged-approvals-v2/specs/staged-approvals/spec.md`.
- v1 change-folder delta (SUPERSEDED): `openspec/changes/hu10-staged-approvals/specs/proposal-approval/spec.md`.
- v2 source requirements that drive the dual-write: REQ-SA-26..36 from `staged-approvals` v2.
- Migration: `migrations/0018_backfill_project_id_and_extend_index.sql` (additive; mirror write to `proposal_approvals` updates `project_id` via the application layer).
- F08 endpoint (unchanged): `app/api/proposals.py` (`decide_proposal`, `modify_proposal`).
- F08 model (unchanged): `app/models/proposal_approval.py` (`ProposalApproval`).

## References

- Issue [#21](https://github.com/danielCH26/arch-agent/issues/21).
- Proposal: `openspec/changes/hu10-staged-approvals-v2/proposal.md` (Engram id 109).
- v1 per-domain delta (SUPERSEDED): `openspec/changes/hu10-staged-approvals/specs/proposal-approval/spec.md`.
- Canonical F08 capability (unchanged): `openspec/specs/proposal-approval/spec.md`.