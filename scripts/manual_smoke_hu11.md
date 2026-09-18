# Manual smoke test — HU11 surgical adjustment

> Issue: [#22](https://github.com/danielCH26/arch-agent/issues/22)
> ADR: [015-hu11-surgical-adjustment](../docs/adr/015-hu11-surgical-adjustment.md)
> Pre-requisito: PR #78 (HU10) mergeado a `development`. Branch `feature/hu11-surgical-adjustment` checked out localmente.

## Setup

```bash
docker compose up -d
# Espera a que Postgres + backend estén healthy (curl http://localhost:8000/health)
cd frontend && npm install && npm run dev
# Abre http://localhost:5173/login
```

Necesitas un usuario creado (vía `/api/auth/register` o el seed del repo) y al menos un provider LLM configurado vía `/api/llm/config` (gpt-4o-mini o qwen3-8b funcionan).

## Flujo 1 — Happy path: 5 fases + edit pasado

### 1.1 Walk-through completo

1. Login → crear proyecto nuevo (nombre: `hu11-smoke-{timestamp}`).
2. **Requerimientos**: responde 5 preguntas del agente → aprobar.
3. **Propuesta**: click `Generar propuesta` → esperar tokens → click `Aprobar`.
4. **Refinamiento**: enviar mensaje que dispare Mermaid (ej. `genera un diagrama de secuencia del flujo de pagos`) → esperar screenshot → click `Aprobar`.
5. **Revisión**: elegir patrón `CQRS`, ventajas/desventajas → click `Aprobar`.
6. **Final**: click `Aprobar` → proyecto archivado.

**Verificación**: GET `/api/projects/{id}/phases` debe devolver 5 fases todas con `status: 'approved'` y `stale: false`.

### 1.2 Surgical adjustment — propuesta aprobada

7. En la UI, click `Editar` en la fila de `propuesta` (ya aprobada).
8. **Esperado**: `<PhaseActions mode='past'>` se monta con banner "Estás editando una fase anterior (propuesta). La fase actual sigue siendo final."
9. Escribir feedback: `agregar capa de cache entre el API gateway y los microservicios`.
10. Click `Regenerar` → SSE stream emite tokens → `event: done` con `{proposal_id: N+1, iteration: 3}`.

**Verificación SQL**:

```sql
-- 1. La fila modify previa sigue presente (audit no se borra)
SELECT id, phase, decision, feedback, previous_output
FROM approvals
WHERE project_id IN (SELECT id FROM projects WHERE name LIKE 'hu11-smoke-%')
ORDER BY id DESC LIMIT 5;

-- 2. proposal_approvals tiene la fila dual-write de la modify decision
SELECT pa.id, p.iteration, pa.decision, pa.previous_output->>'iteration' AS prev_iter
FROM proposal_approvals pa
JOIN proposals p ON p.id = pa.proposal_id
ORDER BY pa.created_at DESC LIMIT 5;

-- 3. Nueva propuesta creada con iteration=max+1
SELECT id, iteration, lifecycle, feedback, content
FROM proposals
ORDER BY iteration DESC LIMIT 3;
```

**Verificación UI**:

- `propuesta.stale = false` (es la fase modificada).
- `refinamiento.stale = true` ⚠ amarillo.
- `revision.stale = true` ⚠ amarillo.
- `final.stale = false`.

### 1.3 Re-aprobar propuesta cleared stale

11. Click `Editar` en propuesta → `Aprobar` (no Regenerar).
12. GET `/api/projects/{id}/phases`:
    - `propuesta.stale = false` (nueva approve row, latest).
    - `refinamiento.stale = false` (propuesta approve nueva es más reciente que refine approve).
    - `revision.stale = false` (idem).

## Flujo 2 — Edge cases que deben manejarse limpios

### 2.1 Doble-click en Regenerar (idempotencia 60s)

```bash
# Toma el decision_id del POST /decision previo (read approvals):
DECISION_ID=$(psql -U asistente -d asistente_db -t -c "
  SELECT id FROM approvals
  WHERE project_id = $PROJECT_ID AND phase = 'propuesta'
  ORDER BY created_at DESC LIMIT 1
")

# Dos POST seguidos a /regenerate con mismo feedback:
curl -sN -X POST http://localhost:8000/api/projects/$PROJECT_ID/phases/propuesta/regenerate \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"feedback":"agregar cache"}' &

curl -sN -X POST http://localhost:8000/api/projects/$PROJECT_ID/phases/propuesta/regenerate \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"feedback":"agregar cache"}' &

wait
```

**Esperado**: ambas respuestas terminan con `event: done`; si los timestamps caen dentro de la ventana 60s del HU10 `IDEMPOTENCY_WINDOW_SECONDS`, la segunda es idempotent (mismo `decision_id`).

### 2.2 LLM 503 mid-stream

```bash
# Configura el provider con un API key inválido para forzar 503:
curl -X POST http://localhost:8000/api/llm/config \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"provider":"openai","api_key":"INVALID","model":"gpt-4o-mini"}'

# Click Regenerar en la UI.
# Esperado:
# - SSE emite event: error con mensaje legible (ej. "401 Unauthorized")
# - UI muestra banner "Reintentar" (no se rompe)
# - La fila approvals previa sigue en DB
```

```sql
SELECT COUNT(*) FROM approvals
WHERE project_id = $PROJECT_ID AND phase = 'propuesta';
-- Debe seguir >= 1 (la fila modify previa está intacta)
```

### 2.3 Past-phase via legacy F05

```bash
# current_phase del proyecto debe ser > 'requerimientos' (avanzar al menos a propuesta)
# Llamada legacy F05 con feedback:
curl -X POST http://localhost:8000/api/projects/$PROJECT_ID/elicitation/decision \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"decision":"modify","feedback":"old client retry"}' -i

# Esperado: HTTP 409 con detail mencionando "regenerate"
# La fila en engram_state["1"]["requerimientos"]["resumen"] NO debe mutar
```

```sql
SELECT engram_state->'$PROJECT_ID'->'requerimientos'->>'resumen'
FROM sessions WHERE user_id = $USER_ID;
-- Debe ser idéntico al valor previo al POST 409
```

### 2.4 final phase regenerate

```bash
curl -X POST http://localhost:8000/api/projects/$PROJECT_ID/phases/final/regenerate \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"feedback":"x"}' -i

# Esperado: HTTP 409 "Modify not allowed on final phase (REQ-SA-8)"
```

### 2.5 Phase ahead of current_phase

```bash
# current_phase=requerimientos; intentar regenerar propuesta:
curl -X POST http://localhost:8000/api/projects/$PROJECT_ID/phases/propuesta/regenerate \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"feedback":"x"}' -i

# Esperado: HTTP 409 con detail mencionando "ahead of current_phase"
```

## Limpieza

```bash
docker compose down -v
```

## Reporte de resultados

Cuando termines, deja un comentario en el PR con:

1. ✅ / ❌ para cada paso del Flujo 1.
2. ✅ / ❌ para cada edge case del Flujo 2.
3. SQL outputs de las verificaciones (pega el resultado en un code block).
4. Tiempo total de la pasada (debe ser < 5 min con gpt-4o-mini).
5. Cualquier desviación respecto al comportamiento esperado.

Si algún paso falla, NO abrir issues separados — el smoke es la verificación de aceptación del PR. Reportar todo en el mismo comentario.