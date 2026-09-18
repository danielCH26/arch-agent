# Guía de pruebas manuales — `feature/hu6-diagrama`

No repite los criterios de aceptación oficiales de HU6. Son casos derivados de lo que realmente cambió en los commits de la rama **más los fixes aplicados durante esta ronda de QA**, listados en la sección 0.

---

## 0. Qué se arregló en esta ronda (léase antes de reportar nada de esto como bug nuevo)

| # | Qué estaba roto | Dónde | Estado |
|---|---|---|---|
| 1 | `_load_approved_proposal_doc` nunca encontraba nada porque nadie escribía `Approval(phase="propuesta", decision="approved")` | Backend — no existía el endpoint | **Arreglado**: `app/api/proposals.py` (nuevo) |
| 2 | No había botón "Rechazar" en la burbuja del chat, solo en el panel de historial | `MessageBubble.tsx` | **Arreglado**: agregado `❌ Rechazar` |
| 3 | Un error del backend al aprobar/rechazar/pedir cambios se perdía en silencio (la UI decía "aprobado" aunque el POST fallara) | `MessageBubble.tsx`, `DiagramHistoryPanel.tsx`, `api/diagrams.ts` | **Arreglado**: ahora se muestra el error en rojo |
| 4 | El panel de historial no mostraba ninguna confirmación después de decidir | `DiagramHistoryPanel.tsx` | **Arreglado**: mensaje verde de confirmación |
| 5 | `fetchDiagramHistory` devolvía `[]` ante cualquier error (401/404/500), indistinguible de "no hay diagramas" | `api/diagrams.ts`, `DiagramHistoryPanel.tsx` | **Arreglado**: ahora distingue error de lista vacía |
| 6 | El warning de "grounding" (`diagram_grounding_warning`) nunca llegaba al usuario — el filtro del frontend lo descartaba junto con otro ruido que comparte el mismo `source: 'agent'` | `api/chat.ts` | **Arreglado**: se muestra en la burbuja, con los nodos no sustentados listados |
| 7 | "Solicitar cambios" mostraba en la burbuja del usuario el prompt técnico completo (instrucciones + Mermaid anterior) en vez de solo su feedback | `chatStore.ts`, `ChatWindow.tsx`, `MessageBubble.tsx`, `api/chat.ts`, `app/api/chat.py`, `app/core/message_store.py`, `app/models/message.py`, **migración 0015** | **Arreglado por completo** — ver nota abajo (ya no es un fix cosmético de sesión) |
| 8 | `.env` con valores entre comillas simples (`POSTGRES_USER='asistente'`) rompe `backend` la próxima vez que se recree, porque la interpolación de Compose no saca las comillas en todos los casos | Infra, no código | **Arreglado en el `.env` del entorno de prueba** — no es parte de la rama, pero anotalo si ves este síntoma en otro entorno |

### Nota actualizada sobre el punto 7 — "Solicitar cambios" (ahora persistente, no solo de sesión)

En la ronda anterior el fix era cosmético (solo duraba la sesión del navegador). Esta ronda cierra ese pendiente con la migración **0015**:

- **Migración nueva**: `messages.display_content` — columna `TEXT NULL`, mismo patrón additive/idempotente que la 0011 (`messages.attachments`). Ver `migrations/0015_add_messages_display_content.sql` y el bloque espejo en `schema.sql` (para DBs creadas desde cero con `init_db.py`).
- `app/models/message.py` — `Message.display_content` (nullable).
- `app/core/message_store.py` — `save_message(...)` acepta `display_content: str | None = None`, con `_coerce_display_content` normalizando strings vacíos/whitespace a `None` (mismo estilo defensivo que `_coerce_citations` / `_coerce_attachments`).
- `ChatRequest` (`app/api/chat.py`) gana el campo opcional `display_message`. Se persiste **solo** en la fila `role="user"` (la fila del asistente nunca tiene `display_content` — no aplica).
- `GET /api/chat/history` devuelve `display_content or content` como `content` — el frontend nunca ve la diferencia, siempre recibe "lo que el usuario vio".
- El frontend (`api/chat.ts`, `chatStore.ts`) manda `display_message` en el POST cuando `displayText` difiere del texto real, y ya no depende de mantenerlo solo en el estado de React.
- **No toca nada de lo que el agente recibe**: `body.message` (el prompt completo con instrucciones + Mermaid anterior) sigue siendo lo único que ve el LLM, en cada turno, tal cual antes.

**Sección 6.1 y la nueva sección 6.3** de esta guía cubren cómo probar esto de punta a punta (incluida la parte que antes NO se podía probar: sobrevivir a un refresh).

Se agregaron tests automáticos para esta parte (ver sección 11): `tests/core/test_message_store.py::TestDisplayContentColumn`, `tests/api/test_chat.py::TestChatRequestDisplayMessage` + 2 tests de integración, `tests/api/test_chat_history.py::TestChatHistoryDisplayContent`, y en frontend `chatStore.test.ts` / `chat.test.ts`. Esto no cubre el resto de la lista de "sin tests automáticos" de la sección 10 (`diagrams.py`, `proposals.py`, sanitizador de Mermaid siguen siendo manuales).

---

## Antes de empezar

- [ ] Stack levantado con Docker Compose (`backend`, `spa`, `postgres-app`, `puppeteer-mcp`, `engram`, etc.)
- [ ] Aplicados los 3 lotes de cambios de la ronda anterior: `app/api/proposals.py` + `server.py` (propuesta), `diagrams.ts` + `DiagramHistoryPanel.tsx` + `MessageBubble.tsx` (botones/errores), `api/chat.ts` (grounding) + `chatStore.ts` + `ChatWindow.tsx` + `MessageBubble.tsx` (display de "Solicitar cambios")
- [ ] **Nuevo**: aplicado el lote de esta ronda — `migrations/0015_add_messages_display_content.sql`, `schema.sql`, `app/models/message.py`, `app/core/message_store.py`, `app/api/chat.py`, `frontend/src/api/chat.ts`, `frontend/src/stores/chatStore.ts`
- [ ] **Corrida la migración 0015**: `docker compose exec backend python migrations/run_migrations.py` (o el runner que uses) — si `backend` se reconstruyó desde una imagen vieja del `.env`, revisá que el contenedor tenga el código nuevo antes de correr esto
- [ ] Verificar que la columna existe: `docker compose exec postgres-app psql -U asistente -d asistente_db -c "\d messages"` → debe listar `display_content | text |`
- [ ] `.env` sin comillas en `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` (y de paso revisá el resto del archivo — mismo riesgo latente en cualquier otra variable con comillas)
- [ ] Si reconstruiste `backend` o `spa`, verificá con `docker compose exec backend printenv DATABASE_URL` que no aparezcan comillas en el valor
- [ ] Dos proyectos del **mismo usuario**: uno con propuesta aprobada y otro sin nada aprobado
- [ ] Un tercer proyecto de **otro usuario**, para las pruebas de aislamiento
- [ ] Hard refresh (Ctrl+Shift+R) después de cualquier rebuild de `spa` — nginx cachea el bundle viejo
- [ ] Consola del navegador (pestaña Network) + `docker compose logs -f backend`
- [ ] Si algo da 500 o "no me deja hacer login" sin razón aparente, lo primero a chequear es si `backend` se recreó recientemente sin querer (por ejemplo, en cascada al recrear otro servicio) — puede haber releído un `.env` con comillas o quedar con variables de entorno de PowerShell pisando el archivo. Cerrar y abrir una terminal nueva antes de sospechar del código.

Para pruebas por API sin pelear con `curl`/PowerShell: `http://localhost:8000/docs` (Swagger). Login → copiar `access_token` → botón **Authorize** arriba a la derecha → `Bearer <token>`.

---

## 1. Generación del diagrama (flujo feliz)

- [ ] En un proyecto en fase de diagrama, pedirle al asistente un diagrama de arquitectura
- [ ] Aparece la imagen PNG debajo de la respuesta de texto
- [ ] `event: diagram_validated` con `valid: true`, `event: attachment` con `kind: screenshot`
- [ ] Click en la miniatura → visor ampliado con zoom funcional
- [ ] Refrescar la página → la imagen sigue viéndose (URL re-firmada por `GET /api/chat/history`)

## 2. Diagramas con texto "raro" (sanitización automática)

- [ ] Nodo con paréntesis sin comillas: `Cliente[Cliente (Web / Mobile)]` → se corrige y renderiza
- [ ] Nodo cilindro/DB: `DB[(Base de datos)]` → no se toca, renderiza igual
- [ ] `subgraph` con acentos y espacios → renderiza con el título completo
- [ ] Línea `class` mezclando IDs y etiquetas con espacio → se limpia/descarta sin tumbar el resto
- [ ] Caso de control: un Mermaid ya válido pasa sin modificaciones

## 3. Diagrama inválido / falla de render

- [ ] Mermaid inválido → `diagram_validated: valid=false` + nota `⚠️` en la burbuja con el error
- [ ] `puppeteer-mcp` caído → el chat sigue respondiendo en texto, `event: degraded` con `reason: render_failed`
- [ ] Nunca se ve un screenshot en blanco ni el error de Mermaid capturado como imagen
- [ ] Puppeteer vuelve a levantar → el siguiente diagrama renderiza sin reiniciar el backend

## 4. Advertencia de "grounding" — ahora sí llega al usuario

- [ ] Proyecto sin RAG/propuesta relevante, pedir un diagrama con componentes inventados
- [ ] En la burbuja del asistente, debajo del diagrama, aparece algo como:
  ```
  Advertencia: El diagrama contiene nodos que no aparecen claramente en el contexto RAG/propuesta aprobada. Nodos: <lista de nodos>.
  ```
  (antes de esta ronda, esto nunca llegaba a la UI — el filtro de `api/chat.ts` lo descartaba)
- [ ] Proyecto con propuesta aprobada que sí menciona esos componentes → la advertencia no aparece
- [ ] Confirmá que la lista de nodos en el mensaje coincide con los que realmente sobran (comparalo contra el Mermaid generado)

## 5. Propuesta aprobada como fuente de verdad

El objetivo de esta sección es validar que los 4 criterios de aceptación de HU6 funcionan de punta a punta con un flujo real (no solo que el endpoint responda bien por separado). No es una lista de bugs a explicar.

- [ ] **Flujo real de HU6**: en Swagger, `POST /api/projects/{id}/proposal/decision` con `decision="approve"` y un `proposal_text` propio y concreto (ej. `"Arquitectura de microservicios: API Gateway, Servicio de Órdenes, Servicio de Pagos, Servicio de Inventario, PostgreSQL"`) → 200. Después, sin salir de ese proyecto, ir al chat y pedirle al asistente que **genere un diagrama de la propuesta aprobada**. Verificar ahí los 4 criterios de HU6: diagrama en Mermaid.js, renderizado a imagen visible, botones de aprobación/modificación (y rechazo) sobre ese diagrama, y que quede en el historial de versiones (sección 7)
- [ ] `POST /api/projects/{id}/proposal/decision` con `{"decision":"approve","proposal_text":"..."}` → 200, `approval_id` con valor, `phase_ready: true`, `proposal_snapshot_chars > 0`
- [ ] `GET /api/projects/{id}/proposal` → refleja lo mismo
- [ ] `modify` sin `feedback` → 400; decisión inválida → 422; proyecto ajeno/inexistente → 403/404
- [ ] `modify`/`reject` después de un `approve` → `phase_ready: false`, `proposal_snapshot_chars: 0` (el snapshot se borra)
- [ ] Con la propuesta aprobada, pedir un diagrama → los nodos coinciden con la propuesta, y en la UI aparece `Fuentes (PGVector): Propuesta aprobada — similitud 100%` (confirmación visual de que se usó el snapshot, no el fallback)
- [ ] En logs del backend, el documento sintético trae `source: session_engram_state` (no `message_id`, que indicaría fallback)
- [ ] Aprobar dos propuestas distintas en el mismo proyecto → el diagrama usa la más reciente
- [ ] Aislamiento: `approvals` cuelga de `sessions` (una fila por usuario, no por proyecto) — aprobar en el proyecto A y pedir diagrama en el proyecto B (sin propuesta propia) puede filtrar por el fallback de historial de chat. Si pasa, es el mismo bug de raíz ya documentado en `elicitation.py`, no algo nuevo.

## 6. Decisiones sobre el diagrama — botones y feedback visual

Hay dos lugares con decisiones, ya con paridad de comportamiento (mensaje verde de éxito / rojo de error en ambos):

| Lugar | Aprobar | Solicitar cambios | Rechazar |
|---|---|---|---|
| Burbuja del chat | sí | sí | sí — agregado en esta ronda |
| Panel Historial | sí | sí | sí (ya existía) |

### 6.1 Burbuja del chat

- [ ] Con un diagrama recién generado: aparecen "Aprobar", "Rechazar", "Solicitar cambios"
- [ ] Aprobar → "Diagrama aprobado." en verde, botones desaparecen, se manda "Apruebo el diagrama, continuemos." al chat
- [ ] Rechazar → "Diagrama rechazado." en verde, botones desaparecen. A diferencia de Aprobar/Solicitar cambios, no manda ningún mensaje al chat (decisión de diseño: rechazar corta el flujo, no pide otra iteración) — si el criterio de aceptación esperaba que sí avisara al agente, es una línea de código a agregar, avisar si hace falta
- [ ] Solicitar cambios → abre textarea; vacío y "Enviar ajuste" → error "Describe el cambio..."; con texto → se manda el prompt completo al agente, pero la burbuja del usuario muestra solo el feedback escrito **y ahora eso persiste** (ver sección 6.3 — ya no se pierde en un refresh, a diferencia de la ronda anterior)
- [ ] Simular error: parar `backend` (`docker compose stop backend`) y hacer click en cualquiera de los tres → mensaje rojo de error, no una falsa confirmación. Levantar backend de nuevo

### 6.2 Panel Historial de diagramas

- [ ] Abrir el panel → Aprobar, Pedir cambios, Rechazar con textarea de feedback compartido
- [ ] "Pedir cambios" con textarea vacío → botón deshabilitado
- [ ] Cualquiera de los tres, con backend arriba → mensaje verde de confirmación debajo de los botones (antes no pasaba nada visible)
- [ ] Parar backend y repetir → mensaje rojo de error (antes tampoco pasaba nada visible)
- [ ] Verificar en DB que las decisiones quedan: `select phase, decision, feedback from approvals where phase='diagram' order by id desc limit 3;`

### 6.3 NUEVO — "Solicitar cambios" sobrevive a un refresh (migración 0015)

Este es el caso que en la ronda anterior estaba explícitamente marcado como "no probar, es esperado que falle". Ahora se prueba así:

- [ ] Con un diagrama recién generado en la burbuja del chat, click en "✏️ Solicitar cambios"
- [ ] Escribir un feedback corto, ej. `Cambiá el color del nodo A a rojo`, click en "Enviar ajuste"
- [ ] La burbuja del usuario muestra **solo** `Cambiá el color del nodo A a rojo` (no el prompt técnico) — esto ya funcionaba antes
- [ ] **Hard refresh de la página (Ctrl+Shift+R)**
- [ ] La burbuja del usuario sigue mostrando `Cambiá el color del nodo A a rojo` — **este es el fix nuevo**. Antes de la migración 0015, acá volvía a aparecer el prompt técnico completo (instrucciones + bloque ```mermaid``` con el diagrama anterior)
- [ ] Verificalo también por API: `GET /api/chat/history?project_id=<id>&limit=5` (Swagger) → el mensaje `role: "user"` correspondiente debe traer `content` = el feedback corto, NO el prompt técnico
- [ ] Verificalo en DB: `select id, role, content, display_content from messages where project_id=<id> order by id desc limit 5;` → la fila `role='user'` de ese turno debe tener `display_content` = el feedback corto y `content` = el prompt técnico completo (son intencionalmente distintos — el agente sigue viendo el prompt completo en cada turno nuevo, esto es solo para lo que se muestra)
- [ ] Enviar un mensaje de chat **normal** (sin pasar por "Solicitar cambios") → en DB, esa fila debe tener `display_content` en `NULL` (no vacío, `NULL`) y `GET /api/chat/history` debe devolver el `content` de siempre — confirma que el fallback `display_content or content` no rompe el caso mayoritario
- [ ] Mensajes viejos, generados **antes** de correr la migración 0015 (si tenés datos de la ronda anterior) → siguen cargando sin error; su `display_content` es `NULL` porque la columna no existía al insertarlos, así que muestran `content` igual que siempre (ningún dato viejo se pierde ni se corrompe)
- [ ] Repetir el flujo completo (Solicitar cambios → refresh → verificar) una segunda vez sobre el mismo proyecto, para confirmar que no es un fluke de la primera vez

## 7. Historial de versiones del diagrama

- [ ] Proyecto sin diagramas → "Todavía no hay diagramas generados en este proyecto." (texto gris, sin error)
- [ ] Generar 2-3 diagramas → listados del más reciente al más antiguo
- [ ] Cerrar y reabrir el panel después de 5+ min → las imágenes siguen cargando (URL re-firmada)
- [ ] Nuevo: proyecto ajeno o backend caído al abrir el panel → mensaje de error en rojo, distinto del texto gris de "no hay diagramas" (antes ambos casos se veían idénticos porque `fetchDiagramHistory` tragaba cualquier error)
- [ ] Confirmar con `curl`/Swagger que un `project_id` de otro usuario da 404 en `GET /api/diagrams/history`

## 8. Rate limit y timeouts de Puppeteer

- [ ] Superar `PUPPETEER_RENDER_RATE_LIMIT_PER_MINUTE` en menos de un minuto → falla controlada, backend sigue de pie
- [ ] Respuesta lenta de `puppeteer-mcp` → cae a "sin diagrama" después de ~15s en vez de colgar el chat

## 9. Regresión rápida del resto del chat

- [ ] Mensaje que no pide diagrama → responde normal, sin llamadas a Puppeteer
- [ ] Historial de chat viejo (sin columna `attachments` ni `display_content`) sigue cargando
- [ ] Elicitación de requerimientos (`/elicitation/message`, `/elicitation/decision`, `/advance`) sigue funcionando sin que el snapshot de propuesta (sección 5) la pise
- [ ] RAG con documentos subidos sigue citando fuentes
- [ ] `POST /api/chat` sin `display_message` en el body (un cliente viejo, o `curl` manual) sigue funcionando igual que siempre — el campo es opcional, `None` por default

## 10. Limitaciones y pendientes conocidos (no reportar como bug nuevo)

- Rechazar en la burbuja no manda mensaje al agente (a propósito, ver 6.1) — confirmar si el criterio de aceptación lo requiere.
- `approvals` no está atado a `project_id` (una sesión por usuario) — riesgo de fuga de contexto entre proyectos del mismo usuario, documentado en `elicitation.py` y reproducible también para propuestas (sección 5, aislamiento).
- No hay tests automáticos para `app/api/diagrams.py`, `app/api/proposals.py`, ni para el sanitizador de Mermaid — todo lo de las secciones 2, 5, 6.1 y 6.2 sigue siendo manual hoy. (La pieza de `display_content`, sección 6.3, sí tiene tests — ver sección 11.)
- Test `client.test.ts > redirects to /login on 401` es flaky (falla también sin nuestros cambios, confirmado con `git stash`) — no relacionado a HU6.
- Si el `.env` tiene valores entre comillas simples y algún servicio se recrea (aunque sea en cascada, sin que lo pidas explícitamente), `backend` puede levantar con credenciales de Postgres literalmente entre comillas y todo el login/chat empieza a dar 500. Revisar `docker compose exec backend printenv DATABASE_URL` ante cualquier 500 repentino después de un `up`/`restart`.

## 11. Tests automáticos agregados esta ronda (migración 0015 / display_content)

Cobertura nueva, para que QA sepa qué ya corre en CI y qué sigue siendo manual:

| Archivo | Qué cubre |
|---|---|
| `tests/core/test_message_store.py::TestDisplayContentColumn` | `save_message(..., display_content=...)` guarda y devuelve el valor; `_coerce_display_content` normaliza `None`/vacío/whitespace a `None` y descarta valores no-string; un mensaje con `display_content` no afecta a los demás en `list_recent` |
| `tests/api/test_chat.py::TestChatRequestDisplayMessage` | El modelo `ChatRequest` acepta `display_message` opcional, default `None` |
| `tests/api/test_chat.py::test_chat_stream_persists_display_message_only_on_user_row` | Integración end-to-end del POST `/api/chat`: `display_message` se persiste en la fila `role="user"`, nunca en la de `role="assistant"` (requiere Postgres de test levantado, igual que el resto de `test_chat.py`) |
| `tests/api/test_chat.py::test_chat_stream_display_message_omitted_keeps_display_content_none` | Caso mayoritario (sin `display_message`): `display_content` queda `None`, sin regresión |
| `tests/api/test_chat_history.py::TestChatHistoryDisplayContent` | `GET /api/chat/history` devuelve `display_content or content`; filas pre-migración (sin `display_content` seteado) no se rompen |

Correrlos:
```bash
# Backend
docker compose exec backend pytest tests/core/test_message_store.py tests/api/test_chat.py tests/api/test_chat_history.py -v

# Frontend
docker compose exec spa npm test -- chatStore.test.ts chat.test.ts
```

Los tests de `tests/api/test_chat.py` (igual que el resto del archivo, no es algo nuevo de esta ronda) necesitan la Postgres de test levantada — si corrés pytest fuera de Docker sin esa DB a mano, vas a ver errores de conexión que no tienen nada que ver con el código nuevo.

---

### Qué reportar en cada bug

Paso exacto, resultado esperado vs. obtenido, `project_id` y usuario usado, y el payload del evento SSE relevante (`diagram_validated` / `degraded` / `attachment`) o la respuesta HTTP, copiada de la consola/Network/Swagger.
