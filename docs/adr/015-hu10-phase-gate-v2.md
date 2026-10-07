# ADR-015: HU10 v2 — Per-stage approval gate with project scoping

**Fecha:** 2026-09-27
**Estado:** Aceptado (supersedes ADR-014)
**Decisor:** Daniel
**Issue:** #21 ([HU10] Aprobar o rechazar cada etapa del flujo)
**Change:** `hu10-staged-approvals-v2` (proposal.md, spec.md, design.md)
**Supersedes:** ADR-014 (`docs/adr/014-hu10-phase-gate.md`)

## Contexto

PR #78 (`feature/hu10-staged-approvals`) returned **CHANGES_REQUESTED** with 4 hard blockers + 7 important findings + 109 files / 18.3 k LoC of scope creep (F13 Puppeteer, F12 Engram, F11, F08 cherry-pick, migration renumber, demo_user lock). The feature does not work in production:

- `<PhaseActions>` never mounts because the SSE `phase_locked` consumer is missing and nothing outside tests calls `approvalsStore.setPending`.
- `approvals` lacks `project_id` — decisions cross-contaminate across projects of the same user (because `sessions.user_id` is UNIQUE, all of a user's projects share one session_id, and the existing 0015 index `idx_approvals_session_phase_created` reads through that single session row).
- `record_decision` validates `phase in AVAILABLE_PHASES` but not `phase == project.current_phase` — any phase can be approved in any order, bypassing the gate.
- The frontend reads `err.data.current_decision` instead of `err.data.detail.current_decision` (FastAPI wraps the body in `detail`).
- A 60-second blanket idempotency window blocks legitimate `modify -> approve` flows.
- No `SELECT FOR UPDATE` — concurrent double-clicks race and produce duplicate rows.
- `window.prompt` returns `null` and was treated as a reject confirmation.
- `previous_output` was `{}` for most phases and in `revision` stored the new payload instead of the prior one.
- The backend leaks `str(exc)` to clients.
- `get_latest_decision` is an unused helper left in the surface area.
- F05, F08, and HU10 all write `projects.phase_ready` independently — no canonical owner.

ADR-014 (`docs/adr/014-hu10-phase-gate.md`) recorded the v1 contract (single canonical `approvals` table, dual-write to `proposal_approvals`, `event: phase_locked` SSE, `previous_output` JSONB). The v1 shape is preserved in spirit; v2 tightens the contract to close all 11 review findings.

## Opciones

| Opcion | Descripcion | Pros | Contras | Veredicto |
|---|---|---|---|---|
| **A** | Cherry-pick PR #78 wholesale and fix forward | Reuses ~18 k LoC of work | Scope creep persists (F13 Puppeteer, F12 Engram, F11, F08, migration renumber, demo_user lock); review budget blown; 11 findings unresolved | Rechazado |
| **B** | Cherry-pick v1 file-by-file then rebase on `development` | Reuses clean v1 files (e.g. `phase_decisions.py` shape, `/phases` skeleton) without scope creep | Fragile merge; v1 files were built on a CHANGES_REQUESTED base; risk of carrying v1 anti-patterns | Rechazado |
| **C** | **Fresh branch from `development`** with tight HU10-only scope and all 11 findings closed as formal REQs (REQ-SA-26..36) | Clean diff; ~600-800 LoC; 1 PR OR a chained-PR plan from `feature/hu10-tracker`; ADR-015 records the v2 contract | Re-implements work that v1 already did; small risk of stale references to v1 surface area | **Elegido** |

## Decisión

**HU10 v2 owns** `propuesta`, `refinamiento`, `revision`, `final` (4 of 5 phases). **F05 owns** `requerimientos` (already wired in `app/api/elicitation.py:211`). The ownership is enforced at `/advance` time and at the row-write layer.

### Concrete contract

1. **Schema**: migration `0017_add_project_id_to_approvals.sql` adds `project_id BIGINT` (FK to `projects(id) ON DELETE CASCADE`), backfills from `sessions.project_id`, creates index `ix_approvals_project_phase_created ON approvals(project_id, phase, created_at DESC)`, and drops the v1 `idx_approvals_session_phase_created`. Idempotent (`IF NOT EXISTS` / `IF EXISTS`).

2. **Domain helper** (`app/core/phase_decisions.py`):
   - Filter by `(project_id, phase)` (NOT session_id) — REQ-SA-27.
   - Acquire `SELECT ... FOR UPDATE` on the `projects` row before INSERT — REQ-SA-31.
   - Reject with 409 when `phase != project.current_phase` — REQ-SA-28.
   - Idempotency key = `(action, payload_hash)`; identical retries return 200 idempotent; different-action retries are accepted within the 60s window — REQ-SA-30.
   - Typed exception `DecisionConflict` carries `{current_decision, decided_at, current_phase}` mapped to FastAPI `HTTPException(409, detail={...})` — REQ-SA-9, REQ-SA-34.

3. **Endpoint** `GET /api/projects/{id}/phases` returns `{phases, current_phase, phase_ready, pending_decision}` — top-level `pending_decision` enables the frontend mount path that was broken in v1 — REQ-SA-12, REQ-SA-26.

4. **Endpoint** `POST /api/projects/{id}/phase/{phase}/decision` returns typed 409 body `{detail: {current_decision, decided_at, current_phase}}`; never `str(exc)` — REQ-SA-15, REQ-SA-34.

5. **Frontend** `approvalsStore` reads `err.data.detail.*` (NOT `err.data.current_decision`) and surfaces a typed `ApiConflictError`. Integration test asserts the real HTTP error body shape end-to-end — REQ-SA-29.

6. **Frontend** `ChatWindow` mounts `<PhaseActions>` from `pendingDecision` derived from the `/phases` response — defense-in-depth alongside the SSE `phase_locked` consumer — REQ-SA-26.

7. **Frontend** `<PhaseActions>` fixes the Tailwind bug (`text-white` on Aprobar), drops `window.prompt`, and renders a new inline `<RejectDialog>` component — REQ-SA-32.

8. **Field rename** for `revision` only: canonical `approvals.current_output`; `approvals.previous_output` retained as a one-release deprecation alias — REQ-SA-33.

9. **`/advance` enforcement**: for HU10-owned phases, verify the HU10 approval row exists before flipping `phase_ready`; F05 retains sole write to `requerimientos` — REQ-SA-36.

10. **Retire** `get_latest_decision` from the surface (REQ-SA-35) and the v1 `mark-ready` endpoint (REQ-SA-23, already removed in v1 branch).

## Consecuencias

### Positivas

- **All 11 PR #78 findings closed** as formal, test-backed requirements (REQ-SA-26..36).
- **Cross-project isolation** is structurally guaranteed by the schema (`project_id NOT NULL` enforced at write time) — the v1 contamination is impossible to recreate.
- **Race protection** via row-level lock on `projects`; concurrent double-click test runs against Postgres (NOT SQLite).
- **Idempotency unblocks `modify -> approve`** — the v1 blanket window was the worst UX bug; v2 key derivation is per-action and per-payload.
- **Single-owner table** makes the `phase_ready` race structurally unreachable; `/advance` is the only writer and it consults the canonical approval record.
- **Frontend mount is defense-in-depth** — SSE `phase_locked` AND `GET /phases pending_decision`. Both paths independently mount `<PhaseActions>`. If one breaks, the other still works.
- **ADR-015 records the v2 contract** with explicit ownership, race policy, idempotency-key derivation, and single-owner table.
- **Single PR <=800 LoC** OR a chained-PR plan from `feature/hu10-tracker` documented before apply.

### Negativas

- **Backfill orphans possible** if a row's `session_id` has no `project_id`. Mitigation: NULL left for manual triage + logged warning; backfill from `sessions.project_id` covers the 99% case.
- **Postgres-only tests** for concurrency — SQLite tests cannot enforce `SELECT FOR UPDATE`. Mitigation: a single Postgres-backed concurrency test is sufficient and the rest stay SQLite.
- **Legacy clients with the v1 idempotency assumption** (any caller that treated the 60s blanket window as authoritative) may observe different retry semantics. Mitigation: deprecation window of one release for the v1 contract.
- **v2 spec REPLACES v1** in `openspec/specs/staged-approvals/spec.md`. Downstream readers expecting the v1 canonical will be redirected by the delta file. Mitigation: the delta explicitly lists REMOVED (none) and MODIFIED (5) entries.
- **F05/F08 dual-write to `phase_ready`** still occurs via their legacy endpoints; v2 only enforces ownership at `/advance`. Mitigation: REQ-SA-36 + ADR-015 documented owner table; F05/F08 unchanged in this PR.
- **Branch from `development`** means we re-introduce the v1 implementation rather than carry it forward. Small risk of duplicating a v1 file's bug fix that has already been merged to `development` via another PR. Mitigation: review the `development` diff first to avoid duplication.

### Neutrales

- `interaction_logs.phase` stays as a free string column; application-layer discipline (already enforced) covers it.
- `previous_output` retained as a deprecation alias for `revision` only (REQ-SA-33).
- `proposal_approvals` mirror retained (REQ-PA-HU10-6) — cleanup is a follow-up PR.

## Referencias

- ADR-014 (`docs/adr/014-hu10-phase-gate.md`) — superseded by this ADR. Historical record retained.
- Proposal: `openspec/changes/hu10-staged-approvals-v2/proposal.md` (Engram id 109).
- Spec: `openspec/specs/staged-approvals/spec.md` (v2, REQ-SA-1..36).
- Spec delta: `openspec/changes/hu10-staged-approvals-v2/specs/staged-approvals/spec.md`.
- Per-domain delta: `openspec/changes/hu10-staged-approvals-v2/specs/proposal-approval/spec.md`.
- Design: `openspec/changes/hu10-staged-approvals-v2/design.md`.
- PR #78 review: Engram id 108 (the 11 raw findings closed by REQ-SA-26..36).
- Migration: `migrations/0017_add_project_id_to_approvals.sql` (idempotent, additive).
- Issue: [#21](https://github.com/danielCH26/arch-agent/issues/21).
- F05 elicitation (unchanged): `app/api/elicitation.py` (owner of `requerimientos`).
- F08 proposals (unchanged): `app/api/proposals.py` (legacy dual-write reader for `propuesta`).
- `migrations/0015_add_previous_output_to_approvals.sql` — v1 migration that introduced `previous_output` JSONB.
- `migrations/0007_add_approvals.sql` — original approvals table (F05).
- `app/models/project.py` — `Project.current_phase`, `Project.phase_ready` referenced by `/advance`.
- `app/models/session.py` — `sessions.project_id` used by migration 0017 backfill.