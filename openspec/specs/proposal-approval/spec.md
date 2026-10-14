# Proposal & Approval — Capability Spec

Capability: `proposal-approval` · Issue: [#12](https://github.com/danielCH26/arch-agent/issues/12) · Branch: `feature/F08-propuesta-aprobacion` · Base: PR #64 `c75b73c` · Source: `proposal.md` `f467154`

> **Actualizada por F10 (trade-offs y aprobación):** REQ-1 a REQ-4 reflejan el comportamiento actual (cinco secciones, citas sin piso fijo, botón "Solicitar alternativas o cambios", tope de iteraciones antes de generar) y REQ-11 añade la tabla de trade-offs. El umbral 0.85 de `RAG_MIN_SIMILARITY` ya solo aplica al chat (ver ADR-009).

## Purpose

`proposal-approval` lets a user in `propuesta` generate an architecture proposal citing RAG patterns, stream it as a `ProposalCard`, and act via Aprobar / Solicitar alternativas o cambios / Rechazar. Relational tables are the source of truth.

## Requirements

### REQ-1
Backend MUST produce a `Proposal` in markdown with the five sections `Componentes`, `Tecnologías`, `Patrones`, `Justificación del patrón principal` and `Trade-offs y decisión`, and persist the markdown text in `proposals.content`. A proposal that is missing any section, or that the model cut off, MUST NOT be persisted nor consume an iteration (SCN-13).

#### SCN-1: Proposal emitted with five sections — AC #1
- GIVEN `project_id=42`, `current_phase="propuesta"`, `phase_ready=true`
- WHEN user clicks "Generar propuesta"
- THEN markdown MUST contain those five headers; `proposals.content` MUST round-trip the markdown.

### REQ-2
Each decision MUST cite `architect_patterns.id` via `proposals.citations[*]`. The proposal phase retrieves the `PROPOSAL_RAG_TOP_N` closest patterns (default 3) from `architect_pattern_chunks` (`PROPOSAL_RAG_CANDIDATE_CHUNKS` chunks grouped by pattern) WITHOUT a fixed similarity floor, because the query is built from the project itself and a floor of 0.85 left the list empty. `PROPOSAL_RAG_MIN_SIMILARITY` (default `0.0`) is an optional floor. `RAG_MIN_SIMILARITY` (0.85) applies to the chat only (ADR-009).

#### SCN-2: Closest patterns are cited in proposals.citations without a fixed floor — AC #2 (positive)
- GIVEN RAG returns `[{id:7, score:0.91}, {id:11, score:0.83}]` and `PROPOSAL_RAG_MIN_SIMILARITY=0.0`
- WHEN stream completes
- THEN `proposals.citations` MUST contain `pattern_id=7, similarity=0.91` and `pattern_id=11, similarity=0.83`.

#### SCN-3: Pattern below the optional floor is filtered from proposals.citations — negative path
- GIVEN same result with `PROPOSAL_RAG_MIN_SIMILARITY=0.85` and no user feedback naming pattern 11
- WHEN stream completes
- THEN `proposals.citations` MUST NOT contain `pattern_id=11`.

### REQ-3
`ProposalActions` MUST render `Aprobar` / `Solicitar alternativas o cambios` / `Rechazar` (the second one keeps `action_type="modify"`); each click MUST POST and insert one `interaction_logs` row with `phase="propuesta"`, `action_type`, `comment?`.

#### SCN-4: Approval action persists interaction_logs row + lifecycle transition — AC #4
- GIVEN `proposals(id=101, lifecycle="proposed")`
- WHEN user clicks Aprobar
- THEN `interaction_logs` row `action_type="approve"` MUST exist, lifecycle MUST become `approved`, `projects.phase_ready=true`.

### REQ-4
"Solicitar alternativas o cambios" (`modify`) MUST create NEW `proposals` row with `iteration = previous + 1`; prior content MUST be preserved in `approvals.previous_output`. `POST /api/proposals/generate` and `/modify` MUST respond `409` BEFORE starting the stream when the next iteration would exceed `PROPOSAL_MAX_ITER` (default 5), counting every proposal of the project, rejected ones included.

#### SCN-5: Feedback creates iteration+1 with previous_output preserved — AC #3
- GIVEN `proposals(id=100, iteration=1)` for `project_id=42`
- WHEN user clicks "Solicitar alternativas o cambios" with `feedback="agregar cache"`
- THEN row `id=101, iteration=2, feedback="agregar cache"` MUST exist; `approvals.previous_output` MUST equal row 100's `content`.

#### SCN-12: Iteration cap rejects the request before generating
- GIVEN the latest proposal of `project_id=42` has `iteration=5` and `PROPOSAL_MAX_ITER=5` (even if it was rejected)
- WHEN user calls `POST /api/proposals/generate`
- THEN the response MUST be `409` with "Has alcanzado el máximo de iteraciones (5)" and no LLM call MUST be made.

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

### REQ-11
Every persisted proposal MUST include, inside `## Trade-offs y decisión`, a markdown table `Opción | Ventajas | Desventajas | Complejidad/costo | Ajuste a requisitos | Fuente RAG` with at least 3 complete rows, followed by `- Recomendación:` and `- Punto de decisión: ¿Aprueba los trade-offs?`. When RAG sources exist, the rows MUST cite at least `min(sources, 3)` distinct existing `[n]`; with fewer than 3 sources the remaining rows MUST be marked `Sin fuente RAG`. The server validates this before persisting.

#### SCN-13: Malformed or cut-off output is not persisted
- GIVEN the model returns a table with fewer than 3 complete rows, rows without a valid `[n]`, no `Recomendación`/`Punto de decisión`, or `finish_reason="length"`
- WHEN the stream ends
- THEN SSE `error` ("incompleta") MUST be emitted, no `proposals` row MUST be written and no iteration MUST be consumed.

#### SCN-14: Fewer than 3 RAG sources are padded and marked
- GIVEN RAG returns 2 patterns
- WHEN the proposal is generated
- THEN the table MUST have rows `[1]` and `[2]` plus a third row marked `Sin fuente RAG`.

#### SCN-15: Tight MVP keeps distributed patterns out of the recommendation
- GIVEN requirements declare a team of at most `PROPOSAL_SMALL_TEAM_MAX` (4) and a timeline of at most `PROPOSAL_SHORT_TIMELINE_MONTHS` (3), even if they say "queremos microservicios"
- WHEN the proposal is generated
- THEN microservicios, Saga and similar patterns MUST appear only as discarded alternatives with their reason, unless the user feedback asks to switch to them.

#### SCN-16: Feedback that removes a pattern keeps it out of the table
- GIVEN user feedback "sin CQRS"
- WHEN a new iteration is generated
- THEN CQRS MUST NOT be cited nor appear as a table row.

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
