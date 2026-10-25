# F08 — Exploration: Propuesta + Aprobación

> Issue: [#12 — [F08] Generación propuesta + aprobación](https://github.com/danielCH26/arch-agent/issues/12)
> Base branch: `origin/feature/Pipeline_RAG_PGVector` (PR #64 OPEN, not merged)
> Our HEAD on this branch: `1159c46` (chore: scaffold openspec)
> Base commit: `c75b73c` (PR #64 HEAD)
> Artifact store: hybrid (OpenSpec + Engram topic `sdd/F08-propuesta-aprobacion/explore`)
> Date: 2026-09-05

## 1. Current State (what the codebase already gives F08)

### 1.1 PR #64 surface that F08 will consume

PR #64 introduces the **RAG pipeline over PGVector** for architecture patterns and uploaded documents. On its HEAD (`c75b73c`) it exposes:

| Path | Kind | Purpose |
|---|---|---|
| `app/api/rag.py` | NEW router | `/api/rag/search`, `/api/rag/patterns/search`, `/api/rag/documents/search` |
| `app/core/rag.py` | NEW core | `similarity_search`, `similarity_search_patterns_by_vector`, helpers `_pattern_to_document`, `_merge_by_distance` |
| `app/models/architect_pattern.py` | NEW model | `ArchitectPattern` (table `architect_patterns`, `embedding vector(384)`) |
| `app/api/chat.py` | MODIFIED | Already calls `similarity_search`, emits SSE `sources` event before tokens, uses `RAG_MIN_SIMILARITY = 0.85` |
| `frontend/src/api/chat.ts` | MODIFIED | SSE parser handles `sources` / `token` / `done` / `error` events |
| `frontend/src/stores/chatStore.ts` | MODIFIED | `Message.sources?: RagSource[]` field |
| `frontend/src/components/MessageBubble.tsx` | MODIFIED | Renders markdown + sources metadata |
| `frontend/src/components/__tests__/MessageBubble.test.tsx` | NEW | 42 lines |
| `migrations/0005_add_architect_patterns.sql` | EXISTS | Creates `architect_patterns` table + ivfflat indexes |
| `scripts/seed_patterns.py` | NEW | 11 patterns across categories `Monolítica` / `Distribuida` / `Patrón de datos` / `Distribuida / Integración`, each with `pattern_name`, `category`, `description`, `use_cases`, `tradeoffs` (JSONB ventajas/desventajas), and an embedding |
| `scripts/limpiar_embeddings_viejos.py` | NEW | Cleanup helper |
| `scripts/seed_bench_vectors.py` | NEW | Benchmark seed |
| `docs/QA_criterios_aceptacion_RAG_final.md` | NEW | QA acceptance criteria, threshold rationale |
| `tests/api/test_rag.py` | NEW | 78 lines, mocks `similarity_search` |
| `app/models/pattern.py` | NEW (duplicate) | Same `ArchitectPattern` class as `app/models/architect_pattern.py`. NOT imported by `app/models/__init__.py` — leftover from a rename. F08 should ignore it. |
| `app/api/users.py`, `frontend/src/pages/ProfilePage.tsx` | NEW | Unrelated (user profile editing, part of PR #64 review comments but orthogonal to F08). |

### 1.2 PR #64 surface that **does NOT** create the `architect_patterns` table

The table comes from `migrations/0005_add_architect_patterns.sql` on `origin/development` (already merged in feature/F03-caso-ejemplo-seed). On PR #64 HEAD:
- `540ae90` renamed its local migration from `0005` → `0006_add_architect_patterns.sql` to avoid clashing with `development`'s already-existing `0005`.
- `c75b73c` (the current HEAD) **deleted** that `0006` migration entirely.
- PR #64's `schema.sql` does NOT define `architect_patterns` either (the `c75b73c` commit removed it).

**Net effect**: after PR #64 merges to `development`, the table still exists (because `development`'s `0005` migration stays). F08 must **NOT** add a new migration for `architect_patterns`. F08 also cannot rely on `init_db.py` on a greenfield DB if `run_migrations.py` has not run — but this is a pre-existing concern, not something F08 introduces.

### 1.3 Existing persistence for the propuesta phase

The `scripts/seed_example.py` end-to-end demo already models the propuesta phase using `sessions.engram_state` JSONB:

```python
engram_state["proposal"] = {
    "patrones_consultados": [...],   # list of {pattern_name, category}
    "patron_recomendado":  "<pattern_name>",
    "aprobacion": {"decision": "approved", "feedback": "..."},
}
```

There is **no** `proposals`, `approvals`, or `interaction_logs` table or model today. The docs-only `docs/database/schema.sql` documents them but no migration exists.

### 1.4 Project conventions that constrain F08

From `openspec/config.yaml` (rules section):
- Backend routers → `app/api/<domain>.py`
- Frontend components → `frontend/src/components/<domain>/`
- React hooks use `use` prefix; state via Zustand stores under `frontend/src/stores/`
- DB schema changes → numbered SQL file under `migrations/`
- LLM-related code → `app/core/llm_*`
- Proposals MUST add an approval lifecycle (`proposed → approved | modified | rejected`) — explicit rule
- F08 stacks on PR #64 base — design MUST be stackable on top of `Pipeline_RAG_PGVector`

From the codebase:
- Backend already has JWT auth (`app/api/dependencies.py::get_current_user`), FastAPI routers, SQLAlchemy 2.0, PGVector.
- Chat is already streaming SSE with sources metadata — F08 inherits this and reuses the `sources` event for citations.
- `app/api/projects.py` already exposes `/api/projects/{id}/advance` and `/api/projects/{id}/mark-ready` for phase transitions; F08 will reuse `phase_ready`.
- `app/core/engram_client.py` is a thin HTTP client to the Engram local server (port 7439). It is used as a product dependency for the agent's memory, NOT for proposal storage.

### 1.5 ADRs that matter for F08

| ADR | Title | Relevant to F08? |
|---|---|---|
| 001 | LangChain framework | YES — the proposal LLM call uses `build_langchain_model(user_id)` (same contract as chat) |
| 002 | PostgreSQL + PGVector | YES — `architect_patterns` and possibly `interaction_logs` live here |
| 003 | multilingual-e5-small embeddings | YES — only relevant if F08 needs to embed anything (it does NOT, since retrieval is delegated to PR #64) |
| 004 | Langfuse observability | YES — every LLM interaction should be traced; F08's `interaction_logs` row is the fallback (mirrors `docs/database/schema.sql`'s comment) |
| 005 | Engram as MCP | PARTIAL — Engram is already a product dependency; F08 MAY mirror the proposal state into Engram for cross-session continuity, but it is NOT a hard requirement (the seed stores proposal only in `sessions.engram_state`) |
| 006 | Chainlit UI | NO — the codebase migrated away from Chainlit (see `app/__init__.py` comment "do NOT import chainlit"). All UI is React+Vite. |
| 007 | Six MCPs | NO — out of scope for F08 |

### 1.6 What "interaction_logs" means for F08

The issue's acceptance criterion "Las iteraciones se registran en interaction_logs" is unambiguous: there must be a relational `interaction_logs` table. The legacy `docs/database/schema.sql` already documents the columns:

```sql
CREATE TABLE interaction_logs (
    id SERIAL PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    phase VARCHAR(50),
    prompt TEXT,
    response TEXT,
    model VARCHAR(100),
    tokens_used INTEGER,
    latency_ms INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

Important mismatch: `docs/database/schema.sql` defines `sessions.project_id NOT NULL REFERENCES projects(id)` whereas the live `schema.sql` defines `sessions.user_id NOT NULL REFERENCES users(id)` with `project_id` nullable. F08 should mirror the **live** schema (user-owned sessions, project optional), matching `app/models/session.py` (implied by `app/models/__init__.py` importing `UserSession`).

The same legacy doc defines an `approvals` table with a `CHECK (decision IN ('approved','modified','rejected'))` — this is also an obvious F08 surface, but optional. Whether F08 uses one table or two depends on the chosen approach.

## 2. Affected Areas (files / surfaces F08 will touch)

- `app/api/proposals.py` — NEW router (F08 owns this name)
- `app/core/proposal_generator.py` — NEW (orchestrates RAG retrieval + LLM drafting)
- `app/core/llm_loader.py` — READ-ONLY (reuse `build_langchain_model(user_id)`)
- `app/core/rag.py` — READ-ONLY (reuse `similarity_search(scope="patterns")`)
- `app/models/proposal.py` — NEW (SQLAlchemy model for the proposal table, if approach chooses relational storage)
- `app/models/interaction_log.py` — NEW (only if approach uses a relational log)
- `app/models/__init__.py` — MODIFIED (register new models)
- `migrations/0008_*.sql` — NEW (proposal / interaction_logs / approvals schema)
- `frontend/src/api/proposals.ts` — NEW (REST client)
- `frontend/src/components/proposals/ProposalCard.tsx` — NEW
- `frontend/src/components/proposals/ProposalActions.tsx` — NEW (Aprobar/Modificar/Rechazar)
- `frontend/src/components/proposals/CitationList.tsx` — NEW (renders patterns with `pattern_id` per acceptance criterion)
- `frontend/src/components/ChatWindow.tsx` — MODIFIED (mount ProposalCard inline when in propuesta phase)
- `frontend/src/stores/proposalsStore.ts` — NEW (Zustand)
- `frontend/src/stores/chatStore.ts` — MINOR (mark the assistant message that produces the proposal)
- `tests/api/test_proposals.py` — NEW
- `tests/api/test_interaction_logs.py` — NEW (if relational log chosen)
- `docs/adr/008-f08-proposal-approval-lifecycle.md` — NEW (documents the lifecycle chosen)

## 3. Approaches

### Approach A — "ProposalCard in chat + relational interaction_logs" (recommended)

End-to-end flow:

1. User is in `current_phase = "propuesta"` and clicks **"Generar propuesta"** (new button in `ChatWindow`, only enabled when `phase_ready` from elicitation is true).
2. Frontend POSTs to `/api/proposals/generate` with `{project_id, feedback?: string}`. For a fresh generation, `feedback` is `null`; for "Modificar" iterations, it carries the user's revision note.
3. Backend (`app/api/proposals.py`) loads the elicitation context (from `sessions.engram_state["elicitation"]`), calls `similarity_search(scope="patterns", k=5)` from `app/core/rag.py`, drafts a proposal via `build_langchain_model(user_id).astream()` using a structured prompt that **requires** citing each cited pattern by `pattern_id`, returns SSE `proposal` + `token` + `citation` + `done` events (reusing the chat SSE pattern).
4. Backend persists:
   - the proposal content + cited `pattern_id`s in a new `proposals` table (JSONB content + `citations: int[]` referencing `architect_patterns.id`);
   - one row in a new `interaction_logs` table per generation (with prompt, response, model, tokens_used, latency_ms);
   - sets `projects.phase_ready = false` until the user decides.
5. Frontend receives the streamed proposal, renders it inside a `ProposalCard` with a `CitationList` component (each citation shows the pattern name + similarity + "ver patrón" link).
6. Below the proposal: an `ProposalActions` panel with three buttons — **Aprobar**, **Modificar**, **Rechazar**.
7. Clicking **Aprobar** POSTs `/api/proposals/{id}/decision` with `{decision: "approved"}` → backend writes an `approvals` row + sets `projects.phase_ready = true`. Frontend hides `ProposalActions` and shows a green chip.
8. Clicking **Modificar** opens a small textarea asking for feedback, then POSTs `/api/proposals/{id}/decision` with `{decision: "modified", feedback}` → backend writes the previous proposal to `approvals.previous_output` (JSONB) and triggers step 3 again with `feedback` included in the prompt, producing a new proposal row. The user iterates.
9. Clicking **Rechazar** POSTs with `{decision: "rejected", feedback?}` → writes the row + reverts `current_phase` to `requerimientos` so the user re-runs elicitation.

| Aspect | Value |
|---|---|
| backend_delta | new `app/api/proposals.py`, new `app/core/proposal_generator.py`, new `app/models/proposal.py`, new `app/models/interaction_log.py`, new `app/models/approval.py`, update `app/models/__init__.py` |
| frontend_delta | new `frontend/src/components/proposals/{ProposalCard,ProposalActions,CitationList}.tsx`, new `frontend/src/api/proposals.ts`, new `frontend/src/stores/proposalsStore.ts`, minor edit to `ChatWindow.tsx` |
| db_delta | 1 new migration `migrations/0008_proposals_and_logs.sql` adding `proposals`, `interaction_logs`, `approvals` |
| depends_on_pr64 | `app/core/rag.py::similarity_search(scope="patterns")`, `app/models/architect_pattern.py::ArchitectPattern`, the SSE pattern in `app/api/chat.py` (replicated, not extended — chat SSE stays untouched) |
| tradeoffs | Best fit for the acceptance criteria (each `pattern_id` is citable, every iteration has a relational row); cleanest rollback; reusable SSE pattern; medium complexity |
| scope_est | M (≈700–900 LoC across backend + frontend + tests + ADR, plus migration) |
| risk | New `proposals` / `interaction_logs` / `approvals` migrations could collide with future PRs that assume these tables don't exist. Mitigation: write the migration idempotently (`CREATE TABLE IF NOT EXISTS`) and document the ownership in `docs/adr/008-f08-proposal-approval-lifecycle.md`. |

### Approach B — "ProposalCard in chat + JSONB-only persistence"

Same UX and same SSE flow as A, but:

- NO new tables. Everything goes into `sessions.engram_state["proposal"]` (current pattern) + `sessions.engram_state["proposal_history"]` (list of versions).
- The "iterations are registered in interaction_logs" acceptance criterion is satisfied by writing JSON snapshots into `sessions.engram_state["interaction_logs"]` — NOT a relational table.

| Aspect | Value |
|---|---|
| backend_delta | new `app/api/proposals.py`, new `app/core/proposal_generator.py`; no new models |
| frontend_delta | same as A |
| db_delta | NONE |
| depends_on_pr64 | same as A |
| tradeoffs | No migration risk; smaller diff; **but** violates the literal acceptance criterion "Las iteraciones se registran en interaction_logs" (a relational table by name) and makes per-iteration queries impossible |
| scope_est | S (≈400–550 LoC) |
| risk | The acceptance criterion is explicit. This approach may force a follow-up PR to add the table later. **Strongly discouraged.** |

### Approach C — "Separate /propuesta page with full-screen editor"

Replace the chat-only flow with a dedicated page:

- `/projects/{id}/propuesta` route with its own `PropuestaPage.tsx`
- A `ProposalEditor` component with two panes: left = Markdown draft (LLM stream), right = live pattern citations panel
- A toolbar at the top with the three actions (Aprobar/Modificar/Rechazar) and a "Regenerar con feedback" inline composer

| Aspect | Value |
|---|---|
| backend_delta | same as A |
| frontend_delta | new `frontend/src/pages/PropuestaPage.tsx`, new route registration, new `frontend/src/components/proposals/ProposalEditor.tsx`, plus all of A's frontend changes |
| db_delta | same as A |
| depends_on_pr64 | same as A |
| tradeoffs | Better UX for large proposals with long citation lists; allows side-by-side comparison between iterations; matches the mockup `mockups-UI/Revision-final.png` more closely (a "Vista de propuesta" with diagrama + trade-offs + aprobación) |
| scope_est | L (≈1100–1400 LoC, exceeds the 400-line review budget without chained PRs) |
| risk | More files to review; risks missing the chat-stream source reuse; requires a router change. Will need **chained PRs** (see Section 5). |

## 4. Recommendation

**Approach A** dominates for F08 v1 because:

1. It is the only option that **literally satisfies** "Las iteraciones se registran en interaction_logs" (the issue acceptance criterion is explicit about the table name).
2. It reuses the existing SSE pattern from PR #64's `app/api/chat.py` rather than inventing a new transport.
3. It keeps the change under the 400-line review budget as a single PR — no chained PRs required. (Estimated ~700–900 LoC, but most of it is straightforward CRUD + a Markdown stream parser; with work-unit commits the per-commit diff stays well under 400.)
4. Rollback is clean: drop migration 0008 and delete the new files.

Approach B is rejected on the literal acceptance criterion. Approach C is appealing UX-wise but doubles the frontend surface; we can revisit it as a follow-up enhancement PR after Approach A lands, or scope it down by mounting the editor inline in `ChatWindow` as a modal (a hybrid A+C if user feedback later shows the inline card is too cramped).

## 5. Delivery strategy notes

- **Stacked on PR #64**: Approach A only consumes `app/core/rag.py`, `app/models/architect_pattern.py`, and the SSE event pattern. None of these are likely to change in PR #64 before it merges. If a future change to PR #64 renames `similarity_search`, F08's `proposal_generator` will need a one-line update.
- **Single PR vs chained**: with `review_budget_lines: 800` per the session preflight, Approach A's ~700–900 LoC sits at the boundary. We should plan it as a single PR with **work-unit commits** (per `work-unit-commits` skill): one commit per work unit (DB migration + interaction_logs model; proposals model + approvals model; proposals API endpoint; proposal_generator core; chat SSE replication; frontend ProposalCard+Citations; frontend ProposalActions+Zustand store; tests + ADR). If at any point a commit's diff exceeds 400 lines, split the implementation into two chained PRs at that boundary.
- **`strict_tdd: false`**: tests are required (per project convention) but the red-green-refactor ceremony is NOT. We will write tests alongside each work-unit commit, per `openspec/config.yaml` `rules.apply`.

## 6. Open ambiguities the proposal phase MUST resolve

1. **"Iterate on the proposal" semantics** — confirmed to be **regenerate-with-feedback** (new proposal row per iteration, old preserved in `approvals.previous_output`), NOT edit-in-place. The acceptance criterion "el usuario puede iterar" + the seed's "Modifica" semantics align with this.
2. **interaction_logs table** — does not exist yet. F08 creates it. The legacy `docs/database/schema.sql` documents the columns; we adopt them with one adjustment (`sessions` schema is user-owned, not project-owned in the live codebase).
3. **"Aprobar / Modificar / Rechazar" UX** — embedded inside the existing chat (`ProposalActions` panel below the streamed proposal), NOT a separate page. This matches the existing chat-centric architecture (`ChatWindow` + `chatStore`) and the `mockups-UI/Chat-elicitacion.png` reference. If the user wants a separate page, we switch to Approach C.
4. **Sync vs async generation** — streaming SSE (same pattern as `app/api/chat.py`), reusing `SSEStreamCallbackHandler`. The user sees tokens as they arrive and a final "proposal ready" event.
5. **Data model for a propuesta** — minimal field set: `id`, `project_id`, `iteration` (int, monotonic per project), `content` (TEXT, the rendered markdown), `citations` (JSONB list of `{pattern_id, pattern_name, similarity}`), `created_at`, plus optional `feedback` (TEXT, set when this iteration was a "Modifica"). Acceptance criterion "cada decisión cita el patrón del RAG" is satisfied by the `citations` JSONB column referencing `architect_patterns.id`.
6. **"Generar propuesta" trigger** — explicit user action (button) rather than automatic on entering the propuesta phase. This matches the issue's "Punto de decisión" framing.
7. **What happens on "Rechazar"** — proposal does NOT advance the phase; the user goes back to `requerimientos`. Alternative: stay in `propuesta` and force another iteration. Default to going back (more user-friendly); make this configurable in the proposal phase if QA pushes back.
8. **Engram integration** — out of scope for v1. The seed uses `sessions.engram_state` to mirror the proposal into a session-bound JSONB blob; F08 does the same only as a convenience, NOT as the source of truth. Source of truth = the relational `proposals` table.
9. **Models in `app/models/pattern.py`** — leftover duplicate of `app/models/architect_pattern.py`. Not imported. Should be removed in a small cleanup commit either in F08 or in PR #64 (recommend: leave for PR #64 to handle since it's outside F08's scope).
10. **Spanish vs English UI copy** — all user-facing copy stays in Spanish to match the existing UI (`PhaseBadge`, `MessageBubble`, `ChatInput`).

## 7. Risks

- **PR #64 not merged yet**: F08's branch is based on `c75b73c` (PR #64 HEAD). If PR #64 changes after this exploration (e.g., renames `similarity_search` or removes `ArchitectPattern`), F08's import surface breaks. Mitigation: pin our base to `c75b73c`, rebase only when PR #64 actually merges to `development`. Document the assumed import surface in `docs/adr/008-f08-proposal-approval-lifecycle.md`.
- **Schema drift between docs and live**: `docs/database/schema.sql` is a legacy doc that contradicts the live `schema.sql` (sessions table FK direction, columns). F08 follows the live schema. Any reviewer comments referencing the doc must be reconciled.
- **Migration numbering collision**: PR #64 HEAD already has `migrations/0007_add_document_chunks_indexes.sql`. F08 must use `0008_*`.
- **`architect_patterns` table availability**: PR #64 removed its own migration. F08 must NOT add one. If a greenfield DB runs `init_db.py` without `run_migrations.py`, `architect_patterns` is still created by `init_db.py` (it has the table definition in the live `schema.sql`). No action needed.
- **Streaming SSE complexity on FastAPI + reverse proxy**: PR #64 already configures `X-Accel-Buffering: no` on `app/api/chat.py`. F08 replicates the same headers.
- **Review budget boundary at 800 lines**: Approach A's LoC estimate sits near the preflight's `review_budget_lines: 800`. Use work-unit commits and consider chained PRs only if a single commit exceeds 400 lines.
- **Zustand store bloat**: `chatStore.ts` already carries messages + sources + streaming state. Adding proposal state there would couple unrelated concerns. New `proposalsStore.ts` keeps them separate (Approach A's choice).
- **Engram unavailable**: per session preflight, Engram may be unreachable; we already noted it is NOT the source of truth, so F08 is robust to its absence. (Saving to Engram topic `sdd/F08-propuesta-aprobacion/explore` is also best-effort.)

## 8. Ready for proposal

**Yes.** Approve Approach A. The proposal phase should:

1. Lock the scope to Approach A (relational `proposals` + `interaction_logs` + `approvals`, SSE-streamed `ProposalCard`).
2. Resolve ambiguities 1, 3, 4, 5, 7 (the rest are inferred from existing patterns and need not be re-asked).
3. Plan work-unit commits so no single commit exceeds 400 lines.
4. Author `docs/adr/008-f08-proposal-approval-lifecycle.md` as the design reference for the apply phase.
5. Author `migrations/0008_proposals_and_logs.sql` (idempotent, three tables).
6. Write `app/api/proposals.py` reusing PR #64's SSE handler and RAG helper.
7. Build the `frontend/src/components/proposals/` tree + new `proposalsStore.ts`.
8. Add `tests/api/test_proposals.py` and `tests/api/test_interaction_logs.py` per project convention (`strict_tdd: false` → tests required, not RED-GREEN-REFACTOR).