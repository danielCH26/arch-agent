# ADR-008: F08 — Source of truth relacional para propuestas (rechazando JSONB-only)

**Fecha:** 2026-09-05
**Estado:** Aceptado
**Decisor:** Daniel
**Issue:** #12 ([F08] Generación propuesta + aprobación)
**Change:** `F08-propuesta-aprobacion` (proposal.md `f467154`, spec.md `7a3b2b1`, design.md pendiente)

## Contexto

La fase `propuesta` del pipeline arch-agent necesita persistir, por cada generación e iteración: (a) el contenido de la propuesta con secciones `Componentes / Tecnologías / Patrones`, (b) la lista de `architect_patterns.id` citados por la propuesta, (c) la decisión del usuario (`approved | modified | rejected`) y, cuando es una iteración, una snapshot del contenido previo para auditoría. Hoy la única persistencia es `sessions.engram_state` JSONB (lo usa `scripts/seed_example.py`), pero ese mecanismo no satisface el criterio de aceptación literal del issue #12: **"Las iteraciones se registran en `interaction_logs`"** (nombre de tabla explícito).

El equipo debe decidir dónde vive el dato. La elección impacta: consultas SQL de negocio (auditoría por proyecto, conteo de iteraciones, ranking de patrones citados), rollback ante un rechazo del usuario, observabilidad cruzada con Langfuse, y compatibilidad con la pipeline RAG ya mergeada en PR #64 (`c75b73c`). Cualquier decisión aquí sienta precedente para futuras fases (`diseno`, `refinamiento`, `revision`).

## Decisión

**Elegido: Approach A — nuevas tablas relacionales `proposals`, `interaction_logs`, `approvals` en PostgreSQL 16 + PGVector (mismo motor). Source of truth = PostgreSQL. Engram queda como espejo best-effort, fuera del flujo crítico.**

Las tres tablas se crean vía `migrations/0008_proposals_and_logs.sql` con `CREATE TABLE IF NOT EXISTS` (idempotente, sin colisión con `0007_add_document_chunks_indexes.sql` de PR #64). `proposals.content` y `proposals.citations` son JSONB para mantener flexibilidad de schema (la forma del markdown evolucionará), pero las columnas `lifecycle`, `iteration`, `project_id`, FKs y CHECK constraints son relacionales puros. Cada generación/iteración inserta una fila en `interaction_logs` con `phase='propuesta'`, `action_type`, prompt, response, model, tokens_used, latency_ms — replicando el contrato que ADR-004 ya reservó como fallback de Langfuse. El endpoint `/api/proposals/{id}/decide` actualiza `projects.phase_ready=true` en Aprobar y `projects.current_phase = PROPOSAL_REJECT_REVERTS_TO` (default `requerimientos`) en Rechazar.

## Consecuencias

### Positivas

- **Satisfacción literal del AC** "iteraciones se registran en `interaction_logs`" — el nombre de la tabla deja de ser ambiguo y se convierte en un contrato SQL firme (consultable, indexable, auditable).
- **Transacciones ACID** entre propuesta + interaction_log + approval (un rollback deshace los tres).
- **Defensa en profundidad con Langfuse** (consistente con ADR-004): `interaction_logs` es el fallback de Langfuse, así que las decisiones también quedan cubiertas por observabilidad operacional.
- **Consultas SQL simples** para "¿cuántas iteraciones tuvo el proyecto 42 antes de aprobar?" o "¿qué patrones cita más la propuesta del usuario X?" — imposibles con JSONB-only sin deserializar.
- **Rollback limpio**: `DROP TABLE IF EXISTS approvals, interaction_logs, proposals CASCADE` revierte el cambio sin tocar datos de PR #64.

### Negativas

- **Aumenta el surface del schema**: tres tablas nuevas + cinco índices. Más migraciones que coordinar con PRs futuros.
- **Dos sistemas para guardar el mismo hecho**: PostgreSQL (truth) + Engram (mirror). Si divergen, el operador debe recordar que PostgreSQL gana.
- **JSONB en `content`/`citations`** sacrifica un poco de validación de schema. Se mitiga con tests que validan round-trip (SCN-1).

### Neutrales

- **Sin impacto en la pipeline RAG**: las nuevas tablas NO referencian `architect_patterns` por FK (las citas son por `pattern_id` dentro de `citations` JSONB). Esto permite que un patrón borrado no elimine propuestas históricas.
- **`sessions.id` referencia con `RESTRICT`** (no `CASCADE`): una propuesta sobrevive aunque el usuario empiece otra sesión.

## Alternativas consideradas

### Approach B — JSONB-only (`sessions.engram_state["proposal"]`)

Rechazado. Viola el AC literal "Las iteraciones se registran en `interaction_logs`" (el nombre de la tabla es parte del criterio). Además, imposibilita queries SQL de auditoría y no satisface el contrato de fallback de Langfuse (ADR-004). Lo rescatable: la **forma** JSONB para `content` y `citations` (sub-decisión dentro de Approach A).

### Approach C — página `/propuesta` dedicada con `ProposalEditor` modal

Rechazado para v1. UX más rica (markdown a la izquierda, citas a la derecha) pero excede el `review_budget_lines=800` (≈1 100–1 400 LoC) y duplica superficie de frontend. Se re-evalúa como follow-up si el inline `ProposalCard` resulta cramped en QA.

### Engram-as-MCP espejo obligatorio (no best-effort)

Rechazado. Engram es un binario local con disponibilidad ~99% pero no 100% (puede caer por OOM, reinicio, error de config). Hacerlo obligatorio acopla el flujo crítico a una dependencia opcional y rompe SCN-10 ("Engram caído no bloquea"). El equipo puede promoverlo a obligatorio en una iteración posterior si la operación lo justifica.

## Referencias

- `openspec/changes/F08-propuesta-aprobacion/proposal.md` (`f467154`) — §3 (Approach A vs B vs C), §4 (out of scope), §6 (affected components), §9 (riesgos).
- `openspec/changes/F08-propuesta-aprobacion/spec.md` (`7a3b2b1`) — REQ-2/REQ-3/REQ-4/REQ-5 (acceptance criteria), SCN-4/SCN-5/SCN-6/SCN-10 (scenarios).
- `openspec/changes/F08-propuesta-aprobacion/explore.md` (`2f1c477`) — §3 (Approaches), §5 (delivery strategy).
- `docs/adr/002-postgres-pgvector.md` — justifica PostgreSQL como única DB con extensión vector.
- `docs/adr/004-langfuse.md` — `interaction_logs` como fallback de Langfuse.
- `docs/adr/005-engram-mcp.md` — Engram como memoria MCP (NO fuente de verdad para propuestas).
- PR #64 base `c75b73c` — superficie RAG sobre la que se apila F08.