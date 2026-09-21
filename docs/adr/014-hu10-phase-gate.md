# ADR-014: HU10 — Contrato del phase gate per-etapa

**Fecha:** 2026-09-18
**Estado:** Aceptado
**Decisor:** Daniel
**Issue:** #21 ([HU10] Aprobar o rechazar cada etapa del flujo)
**Change:** `hu10-staged-approvals` (proposal.md `8c17e3d`, spec.md, design.md pendiente)

## Contexto

El flujo arch-agent tiene 4 fases (`requerimientos`, `propuesta`, `refinamiento`, `revision`) en `AVAILABLE_PHASES` (`app/api/projects.py:44`) pero solo dos tienen gate de aprobación hoy:

- F05 cubre `requerimientos` (`app/api/elicitation.py:211`, escribe en `approvals`).
- F08 cubre `propuesta` (`app/api/proposals.py:241`, escribe en `proposal_approvals`).
- `refinamiento` y `revision` **no tienen gate** — `/advance` exige `phase_ready=true` (`app/api/projects.py:223-227`) pero el chat endpoint (`app/api/chat.py:58`) acepta mensajes sin chequear `phase_ready`, y no existe forma explícita de marcar una fase como lista para el usuario.

El issue #21 exige aprobación explícita en cada etapa con KR Laura: **0% de avance sin aprobación**. Eso requiere:

1. Una superficie Aprobar / Modificar / Rechazar **uniforme** en las 5 fases (issue lista Elicitación + Propuesta + Diagrama + Trade-offs + Aprobación final).
2. Bloqueo del auto-advance, defensa-en-profundidad desde el chat.
3. Persistencia transaccional de la decisión, con `previous_output` para preservar el contenido previo en Modify.
4. Compatibilidad hacia atrás con los lectores F05/F08 que aún consultan `approvals` y `proposal_approvals`.
5. Jubilación del endpoint dev `mark-ready` (`app/api/projects.py:256`).

El cherry-pick de F08 backend sobre la rama `feature/integration-f11-f12-f13` ya está documentado en `proposal.md §3.1` y es prerrequisito de este ADR — F08 backend aporta `proposal_approvals`, `proposals`, `interaction_logs` que se convierten en consumers downstream de la decisión genérica.

## Decisión

**Approach A** (de `explore.md §3`): generalizar la tabla `approvals` de F05 para que sea el **source of truth canónico** de las decisiones de fase. Tablas F08 (`proposal_approvals`, `proposals`, `interaction_logs`) quedan como consumidores downstream. ADR-008 y ADR-009 siguen vigentes.

Concretamente:

### 1. Endpoint canónico único

`POST /api/projects/{id}/phase/{phase}/decision` con body `{action: "approve"|"modify"|"reject", feedback?: string, payload?: object}`. Acepta **solo** fases en `AVAILABLE_PHASES = ["requerimientos", "propuesta", "refinamiento", "revision", "final"]`. Valida `phase` y `action` a nivel de FastAPI/Pydantic.

Los endpoints legacy F05 (`/api/projects/{id}/elicitation/decision`) y F08 (`/api/proposals/{id}/decide`) **siguen funcionando** sin cambios — son wrappers del mismo dominio pero expuestos en sus URLs históricas para no romper la SPA en otras ramas.

### 2. Helper de dominio puro

Toda la lógica de decisión vive en `app/core/phase_decisions.py`. Tres funciones públicas:

| Función | Responsabilidad |
|---------|----------------|
| `record_decision(db, project_id, phase, action, feedback, payload)` | Inserta fila en `approvals`, setea `phase_ready`, devuelve `next_phase`. Para `phase="propuesta"` también dispara el dual-write a `proposal_approvals`. Para `action="approve"` + `phase="final"` archiva el proyecto. |
| `get_latest_decision(db, project_id, phase)` | SELECT idempotency window (60s). Usado para resolver 409 vs 200-idempotente. |
| `dual_write_proposal(db, proposal_id, approval_row, payload)` | Solo llamado desde `record_decision` cuando `phase="propuesta"`. INSERT en `approvals` + `INSERT` en `proposal_approvals` en una sola transacción; rollback atómico. |

Las funciones **no abren su propia sesión**: reciben `db: Session` desde el caller (FastAPI route). Esto permite que el endpoint HTTP controle el lifecycle de la transacción, y que el helper sea 100% puro (fácil de testear con SQLite in-memory).

### 3. Modelo de datos

`migrations/0015_add_previous_output_to_approvals.sql`:

```sql
ALTER TABLE approvals
  ADD COLUMN IF NOT EXISTS previous_output JSONB NOT NULL DEFAULT '{}'::jsonb;

-- Widening del CHECK para HU10. El constraint actual es 'chk_approvals_decision'
-- (nombre heredado de la migration 0008). Se reemplaza por el set de verbos del
-- body del endpoint, no por participios pasados.
ALTER TABLE approvals DROP CONSTRAINT IF EXISTS chk_approvals_decision;
ALTER TABLE approvals
  ADD CONSTRAINT chk_approvals_decision
  CHECK (decision IN ('approved', 'modified', 'rejected', 'approve', 'modify', 'reject'));

CREATE INDEX IF NOT EXISTS idx_approvals_project_phase_created
  ON approvals (project_id, phase, created_at DESC);
```

**Decisión clave**: el nuevo CHECK acepta **ambos** formatos — los participios pasados (`approved`, `modified`, `rejected`) que el código F05 ya inserta vía `DECISION_TO_DB` (`app/api/elicitation.py` usa estos), Y las formas imperativas que el endpoint HU10 acepta en el body. Esto evita una migración de datos destructiva sobre filas existentes y previene el bug que la spec original arrastraba (REQ-SA-16 era incompatible con datos preexistentes).

**Confirmado**: el helper `phase_decisions.record_decision` traduce imperativo→participio **antes** del INSERT, así el contenido de `approvals.decision` queda uniforme con los valores pre-HU10:

```python
DECISION_TO_DB = {"approve": "approved", "modify": "modified", "reject": "rejected"}
```

### 4. Semántica de Modify por fase

| Phase | Modify significa… | Implementación |
|-------|-------------------|----------------|
| `requerimientos` | Re-prompt LLM con feedback | `phase_decisions.record_decision` deja `phase_ready=false`; el frontend dispara `/elicitation/message` con el feedback embebido. |
| `propuesta` | Re-prompt LLM con feedback | `phase_decisions.record_decision` deja `phase_ready=false` y dispara dual-write; el frontend dispara `/api/proposals/{id}/modify`. |
| `refinamiento` | Re-prompt LLM vía F11 para regenerar Mermaid | `phase_decisions.record_decision` deja `phase_ready=false`; el frontend dispara un mensaje al chat agent que invoca `puppeteer_screenshot`. |
| `revision` | Edit UI directo de `{patron_elegido, ventajas, desventajas}` | `PhaseFeedbackComposer` permite editar; al confirmar POST con `action="modify"` + `feedback` describiendo los cambios + `payload={patron_elegido, ventajas, desventajas}`. |
| `final` | **No hay Modify** — solo Aprobar/Rechazar | `<PhaseActions>` no renderiza el botón para `phase="final"`. Si el usuario necesita cambios, debe ir al flujo "Volver a fase anterior" (out of scope para HU10). |

`previous_output` se popula con un JSON snapshot del contenido que está siendo aprobado:
- `requerimientos`: `{resumen: <str>}`
- `propuesta`: `{content: <JSONB>, citations: <JSONB>}`
- `refinamiento`: `{mermaid_source: <str>, attachment_id: <int>}`
- `revision`: `{patron_elegido, ventajas, desventajas}`
- `final`: `'{}'::jsonb` (no hay previous content significativo)

### 5. Chat-side phase gate (defensa en profundidad)

`app/api/chat.py:event_generator` emite `event: phase_locked` **como PRIMER evento** del stream SSE cuando `phase_ready=true` para el `current_phase` del proyecto, **antes** de empezar a streamear tokens. El stream continúa sin refusal — el usuario puede seguir conversando. Esta es la única vía que satisface el AC "0% advance sin approval" sin romper UX legítimos (e.g., follow-up questions después de aprobar).

```python
# Antes de retrieve_context(), en event_generator:
if body.project_id is not None:
    project = db.query(Project).filter(Project.id == body.project_id).first()
    if project and project.phase_ready:
        yield f"event: phase_locked\ndata: {json.dumps({'phase': project.current_phase, 'phase_ready': True}, ensure_ascii=False)}\n\n"
```

Cuando `phase_ready=false`, el stream arranca directo con `event: sources` como hoy — backward compatible con clientes F11/F12/F13 que no saben nada de HU10.

### 6. Dual-write transaccional para `propuesta`

Cuando `phase="propuesta"`, `record_decision` ejecuta en una sola transacción:

```sql
BEGIN;
INSERT INTO approvals (session_id, phase, decision, feedback, previous_output)
VALUES (:session_id, 'propuesta', :decision, :feedback, :previous_output);

-- Solo si el proyecto tiene un proposal_id activo:
INSERT INTO proposal_approvals (proposal_id, decision, previous_output)
VALUES (:proposal_id, :decision, :previous_output);
COMMIT;
-- o ROLLBACK ante cualquier fallo (insert rollback por SQLAlchemy session)
```

`proposal_approvals` queda como **espejo legacy** — los nuevos lectores escriben solo a `approvals`, pero los readers F08 que consultan `proposal_approvals` siguen funcionando. La deprecación se difiere a un PR de cleanup post-F08-frontend-merge.

### 7. Jubilación de `mark-ready`

Se elimina `POST /api/projects/{id}/mark-ready` (`app/api/projects.py:256-286`) y el cliente `markReady` en `frontend/src/api/projects.ts:60-64`. Grep confirma que `mark-ready` solo aparece en estos dos archivos del código activo (sin tests). El reemplazo canónico es la nueva combinación `POST /api/projects/{id}/phase/{phase}/decision` con `action="approve"` + `POST /api/projects/{id}/advance`.

### 8. Modelo de concurrencia

Doble-click en <50ms: el primero gana, el segundo recibe 409. Implementación:

```python
# Antes de INSERT, dentro de la transacción:
existing = (
    db.query(Approval)
    .filter(
        Approval.project_id == project_id,
        Approval.phase == phase,
        Approval.created_at >= datetime.utcnow() - timedelta(seconds=60),
    )
    .order_by(Approval.created_at.desc())
    .first()
)
if existing:
    if existing.action == body.action:
        # 200 idempotente — devolver decision_id original
        return _build_response(existing, idempotent=True)
    raise HTTPException(409, detail={...})
```

REQ-SA-10 del spec HU10 exige ventana de 60s; este código la implementa literalmente. Para cargas simultáneas verdaderas, `SELECT ... FOR UPDATE` con row lock previene la race; el helper usa `with_for_update()` solo en el path de `propuesta` (donde la dual-write hace el lock worthwhile). En otras fases, la idempotency window + `SELECT` regular son suficientes.

## Consecuencias

### Positivas

- **Una sola URL mental** para "aprobar/modificar/rechazar una fase". Onboarding trivial; el frontend no necesita recordar 3 endpoints (F05, F08, genérico).
- **Decisión transaccional** entre `approvals` + `phase_ready` + (para `propuesta`) `proposal_approvals` + `interaction_logs`. Un rollback deshace todo.
- **Source of truth canónico** (`approvals`) + espejo legacy (`proposal_approvals`) + log auditable (`interaction_logs`). Tres capas con roles claros.
- **Defense-in-depth sin 409**: el chat avisa `phase_locked` pero no bloquea mensajes legítimos. El AC "0% advance sin approval" se satisface porque `/advance` sigue exigiendo `phase_ready=true` (no cambia) y porque `event: phase_locked` da al frontend la señal para mostrar un banner "Fase lista — pulsa Avanzar".
- **CHECK dual-form** preserva los datos F05 existentes sin `UPDATE` masivo.
- **Re-prompt vs UI-edit por fase** está documentado per-fase, sin ambigüedad para implementadores futuros.

### Negativas

- **Acoplamiento entre dominios**: HU10 introduce `phase_decisions` que debe coordinarse con `elicitation.decide_elicitation` y `proposals.decide_proposal`. Mitigación: `phase_decisions` es el **único** writer a `approvals` en el código nuevo; los wrappers F05/F08 pueden migrar a llamarlo en un follow-up PR (out of scope HU10).
- **`event: phase_locked` es una adición al contrato SSE**: clientes existentes que parsean el stream asumiendo `sources | token | done | error` ahora ven un evento extra al principio. Mitigación: el frontend `<ChatWindow>` debe ser tolerante a eventos no manejados; ADR-009 ya documentó este patrón (cliente de propuestas ignora `proposal_id` cuando viene `null`).
- **CHECK que acepta 6 verbos** (`approved`, `modified`, `rejected`, `approve`, `modify`, `reject`) es feo: dos formas de decir lo mismo. Mitigación: el helper normaliza antes del INSERT, así los nuevos rows siempre usan participio. Los verbos imperativos se admiten en el CHECK solo como defensa contra writers F05/F08 viejos que pasen el string raw. Se considera la migración de datos post-F08-frontend-merge.
- **Dual-write por `propuesta` solo**: si en el futuro queremos el mismo patrón para otras fases (e.g., `refinamiento` que tiene `diagrams` table), hay que extender `record_decision`. Mitigación: el helper es una sola función con un `if phase == "propuesta": ...` block — fácil de extender.
- **No eliminamos `proposal_approvals` en este PR**: lectores F08 frontend siguen dependiendo. Mitigación: cleanup en PR separado post-F08-frontend merge.

### Neutrales

- **`interaction_logs.phase` queda string libre** (sin CHECK constraint enforcing las 5 fases). Application-layer discipline suficiente para v1.
- **`final` es solo Aprobar/Rechazar**: el AC literal del issue lista 5 fases pero no exige Modify en la quinta. Documentado.
- **`payload` field opcional en el body**: usado por `revision` para enviar `{patron_elegido, ventajas, desventajas}`. Para otras fases el campo se ignora.

## Alternativas consideradas

### Approach B — Tabla nueva `phase_decisions` que subsume ambas

Rechazado en `explore.md §3`. Tres tablas que representan el mismo hecho (`approvals`, `proposal_approvals`, `phase_decisions`) duplican read paths y vuelven la query de "última decisión por (project, phase)" ambigua.

### Approach C — Tablas per-fase (`diagram_approvals`, `tradeoffs_approvals`)

Rechazado. Cuatro tablas + cuatro endpoints + cuatro componentes frontend para una operación conceptualmente idéntica. Excede el budget de review (1100-1400 LoC).

### Approach D — Endpoint genérico + storage per-fase

Rechazado. Mismo problema de read-path ambiguity que B sin el beneficio de tabla unificada. Inventar shapes JSONB para `previous_output` de `diagram_approvals` y `tradeoffs_approvals` es trabajo especulativo (diagram aún no existe como artefacto de primera clase, trade-offs son listas cortas).

### `event: approval_required` en lugar de `phase_locked`

Rechazado por spec. `approval_required` sugiere que el sistema demanda una acción ahora (cliente debería mostrar un modal bloqueante); `phase_locked` solo señala que la fase está cerrada y hay un CTA "Avanzar". El frontend puede mostrar un toast no bloqueante sin romper UX. ADR-009 eligió el patrón SSE consistente con el resto del repo; cambiar el verbo no agrega valor.

### Hard-refuse 409 en `/api/chat` cuando `phase_ready=true`

Rechazado. Si el usuario aprueba `propuesta` y luego tiene un follow-up ("¿y si uso cache?"), el chat DEBE responder — el LLM todavía puede asistir. Un 409 rompería UX legítimos. `phase_locked` + `/advance` ya cubren el 0% advance.

### 200 idempotente siempre (sin 409)

Rechazado. Si el usuario hace doble-click con acciones distintas (approve + reject en 50ms), el segundo debe informar que la primera ganó. 200 silencioso perdería la decisión del usuario.

### Quitar `proposal_approvals` en este PR

Rechazado. Lectores F08 frontend en `feature/F08-s2-frontend` aún dependen. Riesgo de romper una rama no mergeada sin coverage de tests. Cleanup en PR separado.

## Referencias

- Issue [#21](https://github.com/danielCH26/arch-agent/issues/21).
- `openspec/changes/hu10-staged-approvals/explore.md` (Engram id 80) — Approaches A/B/C/D y decisión de base branch.
- `openspec/changes/hu10-staged-approvals/proposal.md` (Engram id 81) — base branch + recipe de cherry-pick.
- `openspec/changes/hu10-staged-approvals/spec.md` — 24 REQ-SA-* canónicos.
- `openspec/changes/hu10-staged-approvals/specs/proposal-approval/spec.md` — 4 REQ-PA-HU10-* delta per-dominio.
- `openspec/specs/staged-approvals/spec.md` — spec canónico (NEW capability).
- `app/api/chat.py:58` — chat endpoint que emite `event: phase_locked`.
- `app/api/elicitation.py:211` — F05 `decide_elicitation` (sin cambios; legacy).
- `app/api/proposals.py:241` — F08 `decide_proposal` (sin cambios; legacy).
- `app/api/projects.py:44`, `:256` — `AVAILABLE_PHASES` y `mark-ready` a jubilar.
- `app/models/approval.py:5` — modelo F05 que recibe `previous_output` JSONB.
- `app/models/proposal_approval.py:6` — modelo F08 que se queda como espejo legacy.
- `app/models/interaction_log.py:5` — log auditable sin cambios de schema.
- `migrations/0007_add_approvals.sql`, `0008_add_approvals_decision_check.sql` — origen de `approvals` + constraint name `chk_approvals_decision`.
- `migrations/0014_proposal_approvals_table.sql` — tablas F08 que reciben dual-write.
- `docs/adr/008-f08-relational-source-of-truth.md` — source of truth relacional.
- `docs/adr/009-sse-pattern-reuse.md` — patrón SSE compartido; HU10 agrega `event: phase_locked` sin romper el contrato.
- Rama base: `feature/integration-f11-f12-f13` HEAD `45db899` + cherry-pick de los 9 commits de F08 backend desde `feature/F08-s2-backend` HEAD `753271a`; merge-base `f5c5251`.