# ADR-009: Reutilización del patrón SSE de `app/api/chat.py` para endpoints F08

**Fecha:** 2026-09-05
**Estado:** Aceptado
**Decisor:** Daniel
**Issue:** #12 ([F08] Generación propuesta + aprobación)
**Change:** `F08-propuesta-aprobacion` (proposal.md `f467154`, spec.md `7a3b2b1`)

## Contexto

El endpoint `POST /api/chat` (`app/api/chat.py` HEAD `c75b73c` PR #64) ya establece un contrato SSE bien definido y probado: emite los eventos `sources | token | done | error`, usa `SSEStreamCallbackHandler` (`app/api/sse.py`) para extraer tokens del callback de LangChain, y envía los headers `Content-Type: text/event-stream`, `Cache-Control: no-cache`, `X-Accel-Buffering: no` (este último crítico para que nginx no bufferise el stream). El frontend ya sabe consumirlo: `frontend/src/api/chat.ts` parsea el buffer en eventos y los entrega a `chatStore`.

F08 necesita stream para `/api/proposals/generate` y `/api/proposals/{id}/modify`. Hay dos opciones: (a) **reutilizar** el patrón existente (eventos idénticos, mismo handler, mismos headers, parser de frontend duplicado pero coherente) o (b) **inventar** un nuevo shape (`proposal | token | citation | done`) porque "las propuestas tienen citas, no solo fuentes". Inventar añade valor si la diferencia semántica lo justifica; de lo contrario, fragmenta la base de código y obliga al frontend a mantener dos parsers SSE diferentes.

## Decisión

**Elegido: reutilizar el patrón SSE de `app/api/chat.py` con cambios mínimos justificados.**

Concretamente:

1. **Mismos eventos**: `sources | token | done | error`. Las citas de propuesta se exponen como `event: sources` con un payload `{pattern_id, pattern_name, similarity}` — el campo `source_type` distingue el origen (`architect_pattern` en lugar de `document_chunk`). El frontend reutiliza `RagSource` con un type guard.
2. **Mismo handler**: `SSEStreamCallbackHandler` de `app/api/sse.py`. Sin reescritura.
3. **Mismos headers**: `Content-Type: text/event-stream`, `Cache-Control: no-cache`, `X-Accel-Buffering: no`. Crítico para no introducir regresiones en el proxy.
4. **`event: done` extendido** con `{proposal_id, citations}` — la única adición. Es backward-compatible: el frontend de chat ignora el payload porque llega `null` (no `proposal_id`); el frontend de propuestas sabe esperar `proposal_id`.
5. **`RAG_MIN_SIMILARITY = 0.85`** se re-declara en `app/api/proposals.py` con el mismo valor. En una iteración posterior podría importarse de un módulo compartido `app/core/rag_config.py`; out of scope v1.
6. **Parser frontend**: `frontend/src/api/proposals.ts` replica la lógica de `frontend/src/api/chat.ts`. La duplicación es aceptable v1 (≈90 LoC) y se unificará en un módulo `frontend/src/api/sse.ts` cuando exista un tercer consumidor.

## Consecuencias

### Positivas

- **Un solo contrato mental** para SSE en todo el repo. Onboarding de nuevos endpoints streaming trivial.
- **Compatibilidad con infraestructura existente**: nginx config, timeouts de Vite dev proxy (`proxyTimeout: 300_000` en `vite.config.ts`), y observabilidad de Langfuse ya validada para `chat.py` aplican sin cambios.
- **Reducción de riesgo de regresión**: el camino feliz de `chat.py` ya está cubierto por `tests/api/test_chat.py::TestSSEFormat`. Cualquier desviación se detecta en code review comparando los dos routers.
- **Menos código nuevo**: ≈30 LoC menos en backend (no reinventamos `_emit_sse` ni el handler) y ≈30 LoC menos en frontend (parser paralelo).

### Negativas

- **Acoplamiento conceptual**: si en el futuro el chat cambia su shape (p.ej. añadir `event: progress`), el endpoint de propuestas queda fuera de sync hasta que alguien lo propague. Mitigación: code-review checklist explícito ("¿cambiaste el SSE de chat? ¿propagaste a proposals?").
- **Re-declarar `RAG_MIN_SIMILARITY`** en dos archivos crea riesgo de divergencia silenciosa. Mitigación: tests que asertan igualdad (`test_rag_threshold_matches_across_modules`).

### Neutrales

- **`event: done` con `proposal_id` es asimétrico** (chat emite `null`, proposals emite `{proposal_id, citations}`). El frontend de chat ignora el JSON parse porque nunca lo lee; el frontend de propuestas sí. Documentado en `frontend/src/api/proposals.ts`.

## Alternativas consideradas

### Inventar `event: proposal`, `event: citation` (shape dedicado)

Rechazado. Aunque la semántica difiere, las diferencias son pequeñas (un campo extra en `sources`, un campo extra en `done`). Inventar un nuevo shape obliga al frontend a mantener dos parsers, fragmenta la documentación y rompe la regla "un patrón por transporte". Si en el futuro F08 necesita eventos genuinamente nuevos (p.ej. `event: pattern_detail` con payload ampliado), se reabre este ADR.

### WebSocket transport

Rechazado. WebSocket es stateful, requiere negociación de subprotocol, y complica el deployment detrás de nginx. SSE es unidireccional server→client (suficiente para F08) y se alinea con el constraint de PR #64. Si una fase futura necesita bidireccionalidad (p.ej. cancelaciones desde el cliente), se reabre este ADR.

### Server-Sent Events vía librería `sse-starlette`

Rechazado. El equipo aún no la usa; introducirla para F08 añade una dependencia solo por estética. El `_emit_sse` inline (≈6 LoC) es trivial y replicable. Se re-evalúa si aparece un tercer consumidor.

## Referencias

- `app/api/chat.py` (`c75b73c`) — implementación de referencia; reusa `SSEStreamCallbackHandler` y emite los headers SSE canónicos.
- `app/api/sse.py` — `SSEStreamCallbackHandler` (LangChain callback → async queue).
- `frontend/src/api/chat.ts` — parser SSE paralelo al que escribiremos en `frontend/src/api/proposals.ts`.
- `frontend/src/api/chat.ts:54` — `callbacks.onToken(data.delta || data)`: referencia para el parser de propuestas.
- `tests/api/test_chat.py::TestSSEFormat` — tests de contrato SSE reutilizados como referencia para `test_proposals.py`.
- `vite.config.ts:27` — `proxyTimeout: 300_000` confirma que el proxy ya soporta streams largos.
- ADR-001 (LangChain framework), ADR-006 (Chainlit UI reemplazada por React; SSE sigue siendo el transporte).