# Proposal & Approval — Capability Spec

Capability: `proposal-approval` · Issue: [#12](https://github.com/danielCH26/arch-agent/issues/12) · Branch: `feature/F08-propuesta-aprobacion` · Base: PR #64 `c75b73c` · Source: `proposal.md` `f467154`

## Purpose

`proposal-approval` lets a user in `propuesta` generate an architecture proposal citing RAG patterns, stream it as a `ProposalCard`, and act via Aprobar / Modificar / Rechazar. Relational tables are the source of truth.

## Requirements

### REQ-1
Backend MUST produce `Proposal` with sections `Componentes`, `Tecnologías`, `Patrones` and persist as `{componentes, tecnologias, patrones: string[]}` in `proposals.content`.

#### SCN-1: Proposal emitted with three sections (Componentes, Tecnologías, Patrones) — AC #1
- GIVEN `project_id=42`, `current_phase="propuesta"`, `phase_ready=true`
- WHEN user clicks "Generar propuesta"
- THEN markdown MUST contain those headers; `proposals.content` MUST round-trip the JSON.

### REQ-2
Each decision MUST cite `architect_patterns.id` via `proposals.citations[*]`, from `similarity_search(scope="patterns", k=5)` filtered by `RAG_MIN_SIMILARITY` (0.85).

#### SCN-2: Pattern above 0.85 threshold is cited in proposals.citations — AC #2 (positive)
- GIVEN RAG returns `[{id:7, score:0.91}, {id:11, score:0.83}]`
- WHEN stream completes
- THEN `proposals.citations` MUST contain `pattern_id=7, similarity=0.91`.

#### SCN-3: Pattern below 0.85 threshold is filtered from proposals.citations — negative path
- GIVEN same result with `RAG_MIN_SIMILARITY=0.85`
- WHEN stream completes
- THEN `proposals.citations` MUST NOT contain `pattern_id=11`.

### REQ-3
`ProposalActions` MUST render `Aprobar` / `Modificar` / `Rechazar`; each click MUST POST and insert one `interaction_logs` row with `phase="propuesta"`, `action_type`, `comment?`.

#### SCN-4: Approval action persists interaction_logs row + lifecycle transition — AC #4
- GIVEN `proposals(id=101, lifecycle="proposed")`
- WHEN user clicks Aprobar
- THEN `interaction_logs` row `action_type="approve"` MUST exist, lifecycle MUST become `approved`, `projects.phase_ready=true`.

### REQ-4
Modificar MUST create NEW `proposals` row with `iteration = previous + 1`; prior content MUST be preserved in `approvals.previous_output`.

#### SCN-5: Modificar feedback creates iteration+1 with previous_output preserved — AC #3
- GIVEN `proposals(id=100, iteration=1)` for `project_id=42`
- WHEN user clicks Modificar with `feedback="agregar cache"`
- THEN row `id=101, iteration=2, feedback="agregar cache"` MUST exist; `approvals.previous_output` MUST equal row 100's `content`.

### REQ-5
`migrations/0008_proposals_and_logs.sql` MUST use `CREATE TABLE IF NOT EXISTS`; FKs to `sessions(id)`, `projects(id)`; `approvals.proposal_id` → `proposals(id)` CASCADE.

#### SCN-6: Migration 0008 rerun is idempotent (table counts unchanged)
- GIVEN migration 0008 already applied
- WHEN `scripts/setup-local.sh` reruns `run_migrations.py`
- THEN the script MUST NOT raise and table counts MUST be unchanged.

### REQ-6
`POST /api/proposals/generate` MUST stream events `sources | token | done | error` (same as `app/api/chat.py`), set header `X-Accel-Buffering: no`; `done` MUST include `proposal_id`.

#### SCN-7: SSE done event payload includes proposal_id
- GIVEN stream for `project_id=42`
- WHEN server emits `event: done`
- THEN payload MUST equal `{"proposal_id": <int>, "citations": [...]}`.

### REQ-7
`ChatWindow` MUST render `ProposalCard` only in `propuesta`; otherwise only `MessageBubble` rows.

#### SCN-8: ProposalCard only rendered in current_phase=propuesta
- GIVEN `current_phase="diseno"`
- WHEN `ChatWindow` renders
- THEN no `ProposalCard` MUST appear in the DOM.

### REQ-8
Rechazar MUST revert `current_phase` to constant `PROPOSAL_REJECT_REVERTS_TO` (default `"requerimientos"`).

#### SCN-9: PROPOSAL_REJECT_REVERTS_TO env override applied on Rechazar
- GIVEN env `PROPOSAL_REJECT_REVERTS_TO="propuesta"`
- WHEN Rechazar fires
- THEN `current_phase` MUST become `"propuesta"`.

### REQ-9
Endpoint MUST persist when Engram (port 7439) is down; Engram errors MUST NOT block DB writes.

#### SCN-10: Engram outage does not block DB persistence
- GIVEN `engram_client.ping()` raises `ConnectionError`
- WHEN proposal generated
- THEN DB rows MUST be written and SSE `done` MUST fire.

### REQ-10
Tests MUST exist: pytest (`test_proposals.py`, `test_interaction_logs.py`), Vitest (`ProposalCard`, `ProposalActions`, `CitationList`). RED-GREEN-REFACTOR NOT required (`strict_tdd=false`).

#### SCN-11: pytest backend + Vitest frontend test suite passes
- GIVEN implementation complete
- WHEN `pytest tests/api/test_proposals.py tests/api/test_interaction_logs.py` runs
- THEN the suite MUST pass.

## Data model

| Table | Columns | FK |
|---|---|---|
| `proposals` | `id`, `session_id`, `project_id`, `iteration INT`, `content JSONB`, `citations JSONB`, `feedback?`, `lifecycle VARCHAR(16) CHECK`, `created_at`, `updated_at` | `sessions(id)`, `projects(id)` CASCADE |
| `interaction_logs` | `id`, `session_id`, `project_id`, `phase`, `action_type`, `comment?`, `prompt?`, `response?`, `model?`, `tokens_used?`, `latency_ms?`, `created_at` | `sessions(id)`, `projects(id)` CASCADE |
| `approvals` | `id`, `proposal_id`, `decision VARCHAR(16) CHECK`, `previous_output JSONB?`, `created_at` | `proposals(id)` CASCADE |

Indexes: `proposals(project_id, iteration)`, `interaction_logs(project_id, phase, created_at)`. SQL DDL ships in migration `0008_proposals_and_logs.sql`.

## Out of scope

JSONB-only Approach B; `/propuesta` page or `ProposalEditor` modal (Approach C); Engram-as-MCP mirror; `app/models/pattern.py` cleanup (PR #64).

## Risks

- PR #64 unmerged — may rename `similarity_search`, `ArchitectPattern`, `SSEStreamCallbackHandler`, `RAG_MIN_SIMILARITY`; rebase gate enforced.
- 800-line budget — chained PRs: `#1` backend ~450 LoC, `#2` SSE+frontend ~300 LoC.
- Migration 0008 ownership collision → `IF NOT EXISTS` + ADR-008.
- `docs/database/schema.sql` drifts from live; F08 mirrors LIVE.
- LLM token cost — configurable cap (default 5).
- 11 SCN labels raise word count above the original 650 budget (~720 expected); acceptable, the explicit labels aid reviewer traceability.

## References

- `explore.md` @ `2f1c477`; `proposal.md` @ `f467154`.
- Issue [#12](https://github.com/danielCH26/arch-agent/issues/12); PR #64 base `c75b73c`.
- `openspec/config.yaml` (`rules.specs` lifecycle; `rules.apply.tdd=false`).
- Engram topic_key: `sdd/F08-propuesta-aprobacion/spec`. Folder: `proposal-approval`.
- AC traceability: SCN-1→AC1, SCN-2→AC2, SCN-3→AC2(negative), SCN-4→AC4, SCN-5→AC3.
