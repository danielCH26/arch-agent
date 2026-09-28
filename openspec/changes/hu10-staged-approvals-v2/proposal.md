# Proposal: HU10 v2 — Per-stage approval gate, scope-bounded, CHANGES_REQUESTED-fixed

> Change folder: `openspec/changes/hu10-staged-approvals-v2/`
> Artifact store: hybrid (this file + Engram topic `sdd/hu10-staged-approvals-v2/proposal`)
> Supersedes: PR #78 (`feature/hu10-staged-approvals`, HEAD `16b5f24`, CHANGES_REQUESTED) — must NOT merge.
> Base branch: `development` (NEVER from PR #78 head, NEVER from `main`).
> Branch name: `feature/hu10-staged-approvals-v2`.
> Issue: [#21](https://github.com/danielCH26/arch-agent/issues/21).

## Intent

PR #78 returned **CHANGES_REQUESTED** with 4 hard blockers + 7 important findings + 109 files / 18.3 k LoC scope creep (F13 Puppeteer, F12 Engram, F11, F08 cherry-pick, migration renumber 0007→0012, demo_user lock). The feature does not work in production because `<PhaseActions>` never mounts — no frontend handler consumes `event: phase_locked` and nothing outside tests calls `setPending`. The `approvals` table lacks `project_id`, so decisions cross-contaminate between projects of the same user (sessions.user_id is unique → all projects share one session_id).

v2 is the corrected change: HU10 only, branched from `development`, single PR ≤ 800 changed lines, all 11 findings closed as formal REQ-SA-26..36 in the canonical spec.

## Scope

### In Scope

- **Blockers → REQ-SA-26..29**:
  - **26** — Frontend consumes `event: phase_locked` in `ChatWindow.tsx` AND `GET /api/projects/{id}/phases` returns `pending_decision`; mount reads it (defense in depth).
  - **27** — `approvals.project_id NOT NULL` + backfill from `sessions.project_id` + index; `record_decision` filters by `(project_id, phase)`.
  - **28** — `record_decision` MUST reject with 409 when `phase != project.current_phase` (no skipping).
  - **29** — `frontend/src/stores/approvals.ts` reads `err.data.detail.current_decision` (FastAPI wraps in `detail`); new integration test with real HTTP error shape.
- **Important findings → REQ-SA-30..36**:
  - **30** — Idempotency key = `(action, payload_hash)` per request; identical retries return 200, different-action retries allowed.
  - **31** — `SELECT ... FOR UPDATE` on project row before INSERT; Postgres concurrent-double-click test (NOT SQLite).
  - **32** — Inline `<RejectDialog>` replaces `window.prompt`; cancel = abort (no reject).
  - **33** — `previous_output` semantics clarified per phase; revision field renamed `current_output`; revision edit IS applied via modify handler.
  - **34** — Typed `ApiConflictError` + structured body; NEVER `str(exc)` to client.
  - **35** — Remove unused `get_latest_decision`.
  - **36** — Single canonical owner of `phase_ready`: **HU10** owns `propuesta`/`refinamiento`/`revision`/`final`; **F05** owns `requerimientos`. `/advance` enforces per-phase.
- Canonical spec REPLACED under `openspec/specs/staged-approvals/spec.md` (v1 copy in repo has content drift vs change folder); delta under `openspec/changes/hu10-staged-approvals-v2/specs/staged-approvals/spec.md` plus `proposal-approval` delta.
- `migrations/0017_add_project_id_to_approvals.sql` — idempotent (`ADD COLUMN IF NOT EXISTS`), backfill, `CREATE INDEX IF NOT EXISTS`. Not destructive.
- ADR-015 (successor to ADR-014): per-phase decision v2 contract covering project_id ownership, race protection, idempotency-key policy.
- Tests: pytest backend (HU10-introduced only); vitest frontend (HU10-introduced only); manual smoke with real LLM recommended pre-merge.

### Out of Scope

- F13 Puppeteer, F12 Engram changes, F11 agent work — separate PRs.
- F05/F08 core behavior — only de-conflict their writes to `phase_ready`; do NOT touch their endpoints.
- Migration renumber 0007→0012 cleanup, deprecation of `proposal_approvals` — separate ops PR / follow-up.
- Multi-user concurrent approval, RBAC, Slack/email notifications, audit log UI, decision history view.
- Real LLM E2E as a merge block (CI smoke is downstream — document the gap, do not block this PR).

## Capabilities

> CONTRACT with sdd-spec. Read `openspec/specs/` before authoring.

### New Capabilities

- `staged-approvals` (canonical). v1 wrote a copy at `openspec/specs/staged-approvals/spec.md` with REQ-SA-5 = "Linear transitions" contradicting the change-folder copy; v2 REPLACES the canonical with REQ-SA-1..36 covering v1 + blocker/important findings + ownership table.

### Modified Capabilities

- `proposal-approval`. Delta acknowledges HU10 owns the `propuesta` lifecycle (REQ-3/REQ-4/REQ-8 stay backward-compat for F08-era readers); `previous_output` continues to mirror prior content.

## Approach

1. Branch `feature/hu10-staged-approvals-v2` from `development`. Cherry-pick of v1 wholesale is forbidden (scope creep). Allow per-file cherry-pick of clean HU10 diffs only.
2. Migration `0017` first (idempotent, additive). Update `schema.sql` mirror.
3. `app/models/approval.py` — add `project_id`; FK to `projects(id)`.
4. `app/core/phase_decisions.py` rewrite: filter by `(project_id, phase)`; reject `phase != current_phase` with 409; `SELECT ... FOR UPDATE` on project row; payload-hash idempotency; typed error bodies.
5. `app/api/projects.py` — `GET /api/projects/{id}/phases` returns `pending_decision` and `phase_ready`; `POST .../phase/{phase}/decision` returns typed 409.
6. Frontend: `approvals.ts` reads `err.data.detail.*`; `PhaseActions.tsx` `text-white` + replace `window.prompt`; new `RejectDialog.tsx` (inline); `ChatWindow.tsx` mounts PhaseActions based on `/phases` response; `phases.ts` typed client.
7. Replace canonical `openspec/specs/staged-approvals/spec.md`; author deltas.
8. ADR-015 + integration tests + Postgres-backed concurrency test.

## Affected Areas

| Area | Impact | Description |
|---|---|---|
| `migrations/0017_add_project_id_to_approvals.sql` | New | idempotent ADD COLUMN + backfill + INDEX |
| `app/models/approval.py` | Modified | add `project_id` FK |
| `app/core/phase_decisions.py` | Modified | project_id filter, FOR UPDATE, current_phase check, payload-hash idempotency |
| `app/api/projects.py` | Modified | `GET /phases` returns `pending_decision`; mount router |
| `app/api/.../decision` | Modified | typed 409 body, payload-hash key |
| `frontend/src/stores/approvals.ts` | Modified | read `err.data.detail.*`; typed `ApiConflictError` |
| `frontend/src/components/PhaseActions.tsx` | Modified | `text-white`; replace `window.prompt` |
| `frontend/src/components/RejectDialog.tsx` | New | inline confirmation |
| `frontend/src/components/ChatWindow.tsx` | Modified | mount PhaseActions from `/phases` response |
| `frontend/src/api/phases.ts` | New | typed `getPhases(projectId)` |
| `openspec/specs/staged-approvals/spec.md` | Replaced | REQ-SA-1..36 (v1 had content drift) |
| `openspec/changes/hu10-staged-approvals-v2/specs/staged-approvals/spec.md` | New (delta) | this change's net new |
| `openspec/changes/hu10-staged-approvals-v2/specs/proposal-approval/spec.md` | New (delta) | HU10 owns propuesta lifecycle |
| `docs/adr/015-hu10-phase-gate-v2.md` | New | successor to ADR-014 |

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Migration backfill orphans (rows without resolvable project_id) | Med | backfill from `sessions.project_id`; NULL left for manual triage + logged warning; not a blocker |
| F05/F08 dual-write to `phase_ready` still races via `/advance` | Med | `/advance` checks HU10 approval record for phases HU10 owns; F05 stays owner of `requerimientos` only; documented in ADR-015 |
| Race regression under double-click | Low | `SELECT FOR UPDATE` + Postgres concurrent-request test (NOT SQLite) |
| 800-line review budget exceeded | Med | proposal commits to chained PRs (hub-and-spoke from `feature/hu10-tracker`) if forecast exceeds 800 lines |
| Replacing canonical spec breaks downstream readers | Low | delta file lists REMOVED REQs explicitly; archive report flags |
| Cherry-pick of v1 branch brings back 18 k LoC scope creep | Med | do NOT cherry-pick wholesale; re-implement tight slice; per-file cherry-pick only after isolating HU10 diff via `git diff feature/hu10-staged-approvals..development -- app/core/phase_decisions.py` |
| E2E gap (no real LLM walk before merge) | Med | recommend manual smoke documented in ADR-015; CI smoke deferred to follow-up |

## Rollback Plan

- Migration `0017` is idempotent + additive (`ADD COLUMN IF NOT EXISTS`, backfill column nullable). Drop = `ALTER TABLE approvals DROP COLUMN project_id`; zero row-data loss.
- All non-DB code reversible by reverting the single PR.
- No destructive schema drops, no data deletion, no `DROP CONSTRAINT` cascades.
- Spec replacement reversible: revert `openspec/specs/staged-approvals/spec.md` to v1 content; delta is additive.
- If `/phases` endpoint causes regressions, behind a feature flag — disabled by default.

## Dependencies

- PR #78 stays open with `CHANGES_REQUESTED`; v2 supersedes — do NOT merge PR #78.
- `development` is current; v2 branches from `development` (NEVER from PR #78 head, NEVER from `main`).
- F05/F08 endpoints unchanged; dual-write for `propuesta` preserved.
- PostgreSQL 16 (NOT SQLite) for tests covering `SELECT FOR UPDATE`.
- ADR-014 (v1) updated/superseded by ADR-015 (not deleted — historical record).

## Success Criteria

- [ ] All 4 reviewer blockers closed with tests (REQ-SA-26..29).
- [ ] All 7 important findings closed (REQ-SA-30..36); typed `ApiConflictError` integration test passes.
- [ ] Migration `0017` applies idempotently; `setup-local.sh` rerun safe; backfill produces 0 orphans in fresh dev DB.
- [ ] No data cross-contamination between projects of same user (integration test: 2 projects, alternating approves, separate `pending_decision`).
- [ ] `<PhaseActions>` mounts in production via `GET /phases` `pending_decision` OR SSE `phase_locked` consumer (verifiable in browser dev tools).
- [ ] pytest green for HU10-introduced code; vitest green for HU10-introduced code.
- [ ] PR diff ≤ 800 changed lines OR chained-PR plan documented with maintainer approval.
- [ ] Canonical `openspec/specs/staged-approvals/spec.md` REPLACED; covers REQ-SA-1..36; delta lists net-new and removed REQs.
- [ ] ADR-015 records: project_id ownership, race policy (`SELECT FOR UPDATE`), idempotency contract (`(action, payload_hash)`), single-owner table per phase.
- [ ] `str(exc)` audit on `app/api/` shows 0 hits in error paths.
- [ ] Single canonical `<PhaseActions>` does not double-render alongside F08-era `ProposalActions` for `propuesta` (orchestrator will verify in CI).

## References

- Engram id 108 (`pr-78-hu10-review`) — full reviewer analysis.
- Engram id 17 (`sdd-init/arch-agent`) — stack, conventions, ADRs.
- `openspec/config.yaml` `rules.proposal` (rollback plan; ADR reference; stacked-PR base).
- `openspec/specs/staged-approvals/spec.md` — v1 copy (TO BE REPLACED by v2).
- `openspec/changes/hu10-staged-approvals/proposal.md` — v1 proposal (superseded).
- Issue [#21](https://github.com/danielCH26/arch-agent/issues/21).
- ADR-014 (v1, historical); ADR-015 (v2 successor) — `docs/adr/015-hu10-phase-gate-v2.md`.
