# Guía de pruebas manuales — `feature/hu6-diagrama`

No repite los criterios de aceptación oficiales de HU6. Son casos derivados de lo que realmente cambió en los commits de la rama **más los fixes aplicados durante esta ronda de QA**, listados en la sección 0.

---

## 0. Qué se arregló en esta ronda (léase antes de reportar nada de esto como bug nuevo)

| # | Qué estaba roto | Dónde | Estado |
|---|---|---|---|
| 1 | `_load_approved_proposal_doc` nunca encontraba nada porque nadie escribía `Approval(phase="propuesta", decision="approved")` | Backend — no existía el endpoint | **Arreglado**: `app/api/proposals.py` (nuevo) |
| 2 | No había botón "Rechazar" en la burbuja del chat, solo en el panel de historial | `MessageBubble.tsx` | **Arreglado**: agregado `❌ Rechazar` |
| 3 | Un error del backend al aprobar/rechazar/pedir cambios se perdía en silencio (la UI decía "aprobado" aunque el POST fallara) | `MessageBubble.tsx`, `DiagramHistoryPanel.tsx`, `api/diagrams.ts` | **Arreglado**: ahora se muestra el error en rojo |
| 4 | El panel de historial no mostraba ninguna confirmación después de decidir | `DiagramHistoryPanel.tsx` | **Superado por el punto 16**: el panel ya no permite decidir (es de solo lectura), así que ya no necesita confirmación |
| 5 | `fetchDiagramHistory` devolvía `[]` ante cualquier error (401/404/500), indistinguible de "no hay diagramas" | `api/diagrams.ts`, `DiagramHistoryPanel.tsx` | **Arreglado**: ahora distingue error de lista vacía |
| 6 | El warning de "grounding" (`diagram_grounding_warning`) nunca llegaba al usuario — el filtro del frontend lo descartaba junto con otro ruido que comparte el mismo `source: 'agent'` | `api/chat.ts` | **Arreglado**: se muestra en la burbuja, con los nodos no sustentados listados |
| 7 | "Solicitar cambios" mostraba en la burbuja del usuario el prompt técnico completo (instrucciones + Mermaid anterior) en vez de solo su feedback | `chatStore.ts`, `ChatWindow.tsx`, `MessageBubble.tsx`, `api/chat.ts`, `app/api/chat.py`, `app/core/message_store.py`, `app/models/message.py`, **migración 0015** | **Arreglado por completo** — ver nota abajo (ya no es un fix cosmético de sesión) |
| 8 | `.env` con valores entre comillas simples (`POSTGRES_USER='asistente'`) rompe `backend` la próxima vez que se recree, porque la interpolación de Compose no saca las comillas en todos los casos | Infra, no código | **Arreglado en el `.env` del entorno de prueba** — no es parte de la rama, pero anotalo si ves este síntoma en otro entorno |
| 9 | `docker compose up -d` no aplicaba el schema ni las migraciones: la DB quedaba sin `messages` y `GET /api/diagrams/history` daba 500 (`relation "messages" does not exist`). Además `scripts/init_db.py` no importaba `os` (`NameError`), `python migrations/run_migrations.py` fallaba con `No module named 'app'` y `scripts/setup-local.sh` tapaba ambos errores con `\|\| warn` | `docker-compose.yml`, `backend/Dockerfile`, `scripts/init_db.py`, `scripts/setup-local.sh` | **Arreglado**: el servicio `backend` corre `init_db.py` + `python -m migrations.run_migrations` antes de uvicorn (si algo falla, el contenedor sale con error y se ve en los logs); `PYTHONPATH=/app` en la imagen; `import os`; `setup-local.sh` ya no oculta errores |
| 10 | El render de diagramas fallaba con `mermaid is not defined`: `mermaid.min.js` (raíz del repo) no se copiaba a la imagen del backend y el código lo leía como string vacío | `backend/Dockerfile` | **Arreglado**: `COPY mermaid.min.js ./` |
| 11 | Con el fix anterior el render fallaba con `unhandled errors in a TaskGroup`: el HTML embebía mermaid.js inline (data URL ≈ 4.5 MB) y `supergateway` (el sidecar de Puppeteer) rechaza cuerpos > 100 KB con HTTP 413 | `app/core/agent.py`, `server.py` | **Arreglado**: el HTML solo referencia `GET /vendor/mermaid.min.js`, que sirve el backend por la red de Docker (sigue sin necesitar internet); el log ahora muestra la causa real (`413`, `ConnectError`...) en vez de `TaskGroup` |
| 12 | Falso positivo en el aviso de grounding: con propuesta `...PostgreSQL` el diagrama rotulaba `Base de Datos PostgreSQL` y se advertía igual (la etiqueta completa debía ser substring del texto de la propuesta) | `app/core/agent.py` | **Arreglado**: un nodo cuenta como respaldado si todas sus palabras distintivas (sin "de", "base", "datos", "servicio"...) aparecen en el contexto; los nodos inventados (`Servicio de Blockchain`, `Base de Datos MongoDB`) se siguen marcando |
| 13 | El schema OpenAPI de `GET /api/diagrams/history` era un objeto genérico (no mostraba la forma de cada diagrama) | `app/api/diagrams.py` | **Arreglado**: `response_model=DiagramHistoryOut` (`diagrams[]` con `message_id`, `id`, `url`, `filename`, `created_at`, `decision`) |
| 14 | Dos tests de `_load_approved_proposal_doc` fallaban: los mocks de `Approval` no traían `decision="approved"` y la función exige que la última decisión sea `approved` | `tests/api/test_chat.py` | **Arreglado** en los tests (el código estaba bien) |
| 15 | Rechazar (o aprobar / pedir cambios) un diagrama no se recordaba: tras un F5 volvían a aparecer los tres botones y había que decidir otra vez. La decisión se guardaba solo por proyecto, sin saber a qué diagrama correspondía, y el estado "ya decidido" vivía solo en la memoria de React | `app/api/diagrams.py`, `app/api/chat.py`, `app/core/session_store.py`, `app/models/approval.py`, `api/chat.ts`, `api/diagrams.ts`, `MessageBubble.tsx`, **migración 0017** | **Arreglado**: la decisión se guarda **por diagrama** — ver nota abajo |
| 16 | El panel Historial permitía aprobar / rechazar / pedir cambios sobre "el diagrama actual" aunque ya se hubiera decidido en el chat (p. ej. aprobado en el chat y rechazado desde el historial) | `DiagramHistoryPanel.tsx` | **Arreglado**: el panel es de **solo lectura**; muestra el estado de cada versión y las decisiones se toman únicamente en el chat |

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

### Nota sobre los puntos 15 y 16 — decisión por diagrama (migración 0017)

- **Migración nueva**: `approvals.attachment_id` — `VARCHAR(64) NULL` con índice, mismo patrón additive/idempotente que 0011, 0015 y 0016. Ver `migrations/0017_add_attachment_id_to_approvals.sql` y el bloque espejo en `schema.sql`. Es el UUID del adjunto (`messages.attachments[].id`, el mismo que va dentro de la URL firmada de la imagen).
- El evento SSE `attachment` ahora trae `id`; `GET /api/chat/history` devuelve por cada adjunto `id` y `decision` (`approve` / `modify` / `reject`, o `null` si no se decidió). Con eso la burbuja recupera el estado tras un F5 y no vuelve a ofrecer los botones.
- `POST /api/diagrams/decision` acepta `attachment_id` (opcional, por compatibilidad con clientes viejos): **404** si el diagrama no existe o es de otro usuario/proyecto; **409** (`Este diagrama ya tiene una decisión registrada.`) si ya tenía decisión. Sin `attachment_id` se comporta como antes (decisión a nivel de proyecto, sin recordarse por diagrama).
- `GET /api/diagrams/history` devuelve `id` y `decision` por versión. El panel las muestra como etiqueta (✅ Aprobado / ❌ Rechazado / ✏️ Cambios solicitados / Sin decisión) y **ya no ofrece botones**.
- **Los diagramas decididos antes de la migración 0017 no tienen `attachment_id`** (la decisión vieja no decía a qué diagrama se refería), así que volverán a mostrar los botones una vez. No es un bug.

Se agregaron tests automáticos para esta parte (ver sección 11): `tests/core/test_message_store.py::TestDisplayContentColumn`, `tests/api/test_chat.py::TestChatRequestDisplayMessage` + 2 tests de integración, `tests/api/test_chat_history.py::TestChatHistoryDisplayContent`, y en frontend `chatStore.test.ts` / `chat.test.ts`. Hoy también existen tests automáticos para `app/api/diagrams.py` (`tests/api/test_diagrams.py`, incluida la decisión por diagrama), `app/api/proposals.py` (`tests/api/test_proposals.py`), el validador/sanitizador de Mermaid (`tests/core/test_mermaid_validator.py`), el render/grounding de `agent.py` (`tests/core/test_agent.py`) y, en frontend, la burbuja y el panel de historial. Lo que sigue siendo manual está en la sección 10.

---

## Antes de empezar

- [ ] Stack levantado con Docker Compose (`backend`, `spa`, `postgres-app`, `puppeteer-mcp`, `engram`, etc.), reconstruido con `docker compose up -d --build` (necesario tras cambiar `Dockerfile`, `app/`, `server.py` o `frontend/`)
- [ ] Aplicados los 3 lotes de cambios de la ronda anterior: `app/api/proposals.py` + `server.py` (propuesta), `diagrams.ts` + `DiagramHistoryPanel.tsx` + `MessageBubble.tsx` (botones/errores), `api/chat.ts` (grounding) + `chatStore.ts` + `ChatWindow.tsx` + `MessageBubble.tsx` (display de "Solicitar cambios")
- [ ] **Nuevo**: aplicado el lote de esta ronda — `migrations/0015_add_messages_display_content.sql`, `schema.sql`, `app/models/message.py`, `app/core/message_store.py`, `app/api/chat.py`, `frontend/src/api/chat.ts`, `frontend/src/stores/chatStore.ts`
- [ ] **Nuevo**: aplicado el lote de decisión por diagrama — `migrations/0017_add_attachment_id_to_approvals.sql`, `schema.sql`, `app/models/approval.py`, `app/core/session_store.py`, `app/api/diagrams.py`, `app/api/chat.py`, `frontend/src/api/chat.ts`, `frontend/src/api/diagrams.ts`, `MessageBubble.tsx`, `DiagramHistoryPanel.tsx`
- [ ] **Migraciones aplicadas** (0015, 0016, 0017...): se aplican solas al arrancar el backend — el `command` del servicio `backend` en `docker-compose.yml` corre `scripts/init_db.py` y `python -m migrations.run_migrations` antes de uvicorn. Confirmalo con `docker compose logs backend` (buscá `N migración(es) aplicada(s).` o `No hay migraciones pendientes.`). Para correrlas a mano: `docker compose exec backend python -m migrations.run_migrations`. Si el backend no levanta, casi siempre es una migración o `init_db` fallando: el error queda en esos logs
- [ ] Verificar que las columnas existen: `docker compose exec postgres-app psql -U asistente -d asistente_db -c "\d messages"` → debe listar `display_content | text |`; y `... -c "\d approvals"` → debe listar `attachment_id | character varying(64) |`
- [ ] La librería de Mermaid la sirve el backend (la usa el render): `curl.exe -s -o NUL -w "%{http_code} %{content_type} %{size_download} bytes`n" http://127.0.0.1:8000/vendor/mermaid.min.js` → `200 application/javascript ...` (usá GET; `curl -I` manda HEAD y da 405 a propósito)
- [ ] El sidecar alcanza al backend por la red de Docker: `docker compose exec puppeteer-mcp wget -S -O /dev/null http://backend:8000/vendor/mermaid.min.js` → `HTTP/1.1 200 OK`
- [ ] `.env` sin comillas en `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` (y de paso revisá el resto del archivo — mismo riesgo latente en cualquier otra variable con comillas)
- [ ] Si reconstruiste `backend` o `spa`, verificá con `docker compose exec backend printenv DATABASE_URL` que no aparezcan comillas en el valor
- [ ] Si `docker compose` imprime `The "XYZ" variable is not set`, algún valor del `.env` contiene un `$`: Compose lo interpreta como variable y lo deja vacío. Escribilo como `$$`. Para ver qué variable es sin mostrar los valores: `Select-String -Path .env -Pattern '\$' | ForEach-Object { ($_.Line -split '=')[0] }`
- [ ] Ojo: `docker compose down -v` borra también la DB (usuarios, proyectos, aprobaciones) — después hay que registrarse de nuevo
- [ ] Dos proyectos del **mismo usuario**: uno con propuesta aprobada y otro sin nada aprobado
- [ ] Un tercer proyecto de **otro usuario**, para las pruebas de aislamiento
- [ ] Hard refresh (Ctrl+Shift+R) después de cualquier rebuild de `spa` — nginx cachea el bundle viejo
- [ ] Consola del navegador (pestaña Network) + `docker compose logs -f backend`
- [ ] Si algo da 500 o "no me deja hacer login" sin razón aparente, lo primero a chequear es si `backend` se recreó recientemente sin querer (por ejemplo, en cascada al recrear otro servicio) — puede haber releído un `.env` con comillas o quedar con variables de entorno de PowerShell pisando el archivo. Cerrar y abrir una terminal nueva antes de sospechar del código.

Para pruebas por API sin pelear con `curl`/PowerShell: `http://localhost:8000/docs` (Swagger). `POST /api/auth/login` (o `/api/auth/register` para crear un usuario) → copiar el campo `token` de la respuesta → botón **Authorize** arriba a la derecha → pegar solo el token (Swagger agrega `Bearer` solo).

Para ver los eventos SSE: F12 → Network → petición `chat` → pestaña **EventStream** (o **Response**): ahí aparecen `diagram_validated`, `attachment` (ahora con `id`) y `degraded`. Para consultar la DB desde PowerShell: `docker compose exec postgres-app psql -U asistente -d asistente_db -c "<consulta>"` (usuario y DB por defecto de `.env.example`; usá los de tu `.env` si los cambiaste).

---

## 1. Generación del diagrama (flujo feliz)

- [ ] Pedirle al asistente un diagrama de arquitectura (no hace falta cambiar la fase del proyecto: alcanza con que el mensaje contenga la palabra "diagrama")
- [ ] Aparece la imagen PNG debajo de la respuesta de texto
- [ ] `event: diagram_validated` con `valid: true`, `event: attachment` con `kind: screenshot` y un `id` (UUID)
- [ ] Click en la miniatura → visor ampliado con zoom funcional
- [ ] Refrescar la página → la imagen sigue viéndose (URL re-firmada por `GET /api/chat/history`)

## 2. Diagramas con texto "raro" (sanitización automática)

- [ ] Nodo con paréntesis sin comillas: `Cliente[Cliente (Web / Mobile)]` → se corrige y renderiza
- [ ] Nodo cilindro/DB: `DB[(Base de datos)]` → no se toca, renderiza igual
- [ ] `subgraph` con acentos y espacios → renderiza con el título completo
- [ ] Línea `class` mezclando IDs y etiquetas con espacio → se limpia/descarta sin tumbar el resto
- [ ] Caso de control: un Mermaid ya válido pasa sin modificaciones

**Forma determinista, sin LLM** (el modelo no siempre escribe justo el texto que querés probar). Creá `qa_sanitizer.py` en la raíz del repo (no lo commitees) y corrélo con el venv activo (`python qa_sanitizer.py`):

```python
from app.core.mermaid_validator import sanitize_mermaid, validate_mermaid

casos = {
    "paréntesis": 'flowchart LR\n  Cliente[Cliente (Web / Mobile)] --> API[API]',
    "cilindro DB": 'flowchart LR\n  API[API] --> DB[(Base de datos)]',
    "subgraph": 'flowchart TB\n  subgraph Capa de Presentación\n    A[UI]\n  end',
    "control válido": 'flowchart LR\n  A["Nodo 1"] --> B["Nodo 2"]',
    "inválido": 'esto no es mermaid',
}
for nombre, codigo in casos.items():
    salida = sanitize_mermaid(codigo)
    print(nombre, "| cambió:", salida != codigo, "| válido:", validate_mermaid(salida))
```

Resultado esperado: `paréntesis` cambia a `Cliente["Cliente (Web / Mobile)"]`; `cilindro DB` y `control válido` no cambian; `subgraph` queda como `Capa_de_Presentacion["Capa de Presentación"]`; todos son válidos salvo `inválido` → `(False, "Tipo de diagrama no reconocido: ...")`. Para el caso de la línea `class` agregá un caso con ese texto y comprobá que el resto de las líneas sobrevive. Esto prueba el sanitizador/validador, no el render: para ver la imagen pedilo también por chat.

## 3. Diagrama inválido / falla de render

- [ ] Mermaid inválido → `diagram_validated: valid=false` + nota `⚠️` en la burbuja con el error
- [ ] `docker compose stop puppeteer-mcp` y pedir un diagrama → el chat sigue respondiendo en texto (con el bloque Mermaid, **sin imagen: es lo esperado**) y en EventStream aparece `event: degraded` con `reason: render_failed`. Solo es un fallo si el chat no responde, se cuelga o muestra un error
- [ ] Nunca se ve un screenshot en blanco ni el error de Mermaid capturado como imagen
- [ ] `docker compose start puppeteer-mcp` → el siguiente diagrama renderiza sin reiniciar el backend. Esperá ~20-30 s tras el `start` (Chromium tarda en arrancar; el healthcheck del compose tiene `start_period: 20s`): un intento anterior puede dar `render_failed` y no es un bug

## 4. Advertencia de "grounding" — ahora sí llega al usuario

- [ ] Proyecto sin RAG/propuesta relevante, pedir un diagrama con componentes inventados
- [ ] En la burbuja del asistente, debajo del diagrama, aparece algo como:
  ```
  Advertencia: El diagrama contiene nodos que no aparecen claramente en el contexto RAG/propuesta aprobada. Nodos: <lista de nodos>.
  ```
  (antes de esta ronda, esto nunca llegaba a la UI — el filtro de `api/chat.ts` lo descartaba)
- [ ] Proyecto con propuesta aprobada que sí menciona esos componentes → la advertencia no aparece. Caso conocido: la propuesta dice `PostgreSQL` y el diagrama rotula `Base de Datos PostgreSQL` → **no** debe advertir (antes sí, era un falso positivo; ver fila 12 de la sección 0)
- [ ] Con esa misma propuesta, pedir un componente que no está (ej. "agregá un Servicio de Blockchain y una Base de Datos MongoDB") → la advertencia **sí** aparece y lista esos nodos
- [ ] Confirmá que la lista de nodos en el mensaje coincide con los que realmente sobran (comparalo contra el Mermaid generado)
- [ ] **Corregido** (ver sección 10) — si el LLM rotula un nodo con comillas literales dentro del label (ej. el nodo se ve como `"API Gateway"` dentro del recuadro), la lista de nodos de la advertencia ya no muestra el texto crudo `#quot;API Gateway#quot;`: `_add` (`_extract_mermaid_node_names`, `agent.py`) revierte el escape antes de armar el mensaje. Probarlo con un nodo tipo `Cliente["Cliente #quot;Premium#quot;"]` y confirmar que la advertencia muestra `Cliente "Premium"`, nunca `#quot;`.

## 5. Propuesta aprobada como fuente de verdad

El objetivo de esta sección es validar que los 4 criterios de aceptación de HU6 funcionan de punta a punta con un flujo real (no solo que el endpoint responda bien por separado). No es una lista de bugs a explicar.

- [ ] **Flujo real de HU6**: en Swagger, `POST /api/projects/{id}/proposal/decision` con `decision="approve"` y un `proposal_text` propio y concreto (ej. `"Arquitectura de microservicios: API Gateway, Servicio de Órdenes, Servicio de Pagos, Servicio de Inventario, PostgreSQL"`) → 200. Después, sin salir de ese proyecto, ir al chat y pedirle al asistente que **genere un diagrama de la propuesta aprobada**. Verificar ahí los 4 criterios de HU6: diagrama en Mermaid.js, renderizado a imagen visible, botones de aprobación/modificación (y rechazo) sobre ese diagrama, y que quede en el historial de versiones (sección 7)
- [ ] `POST /api/projects/{id}/proposal/decision` con `{"decision":"approve","proposal_text":"..."}` → 200, `approval_id` con valor, `phase_ready: true`, `proposal_snapshot_chars > 0`
- [ ] `GET /api/projects/{id}/proposal` → refleja lo mismo
- [ ] `modify` sin `feedback` → 400; decisión inválida → 422; proyecto ajeno/inexistente → 403/404
- [ ] `modify`/`reject` después de un `approve` → `phase_ready: false`, `proposal_snapshot_chars: 0` (el snapshot se borra)
- [ ] Con la propuesta aprobada, pedir un diagrama → los nodos coinciden con la propuesta, y en la UI aparece `Fuentes (PGVector): Propuesta aprobada — similitud 100%` (confirmación visual de que se usó el snapshot, no el fallback)
- [ ] (Opcional, si tu build lo loguea) el documento sintético trae `source: session_engram_state` y no `message_id`, que indicaría fallback. La evidencia principal es la línea `Fuentes (PGVector)` de la UI
- [ ] Aprobar dos propuestas distintas en el mismo proyecto → el diagrama usa la más reciente
- [ ] Aislamiento: `approvals` ahora lleva `project_id` (migración 0016) y `_load_approved_proposal_doc` filtra por proyecto. Aprobar en el proyecto A y pedir diagrama en el proyecto B (sin propuesta propia) → B **no** debe recibir la propuesta de A (no debe salir `Fuentes ... Propuesta aprobada`). Si pasa, es un bug real. Además, si la última decisión del proyecto es `modify`/`reject`, una aprobación anterior ya no se usa, y las filas viejas con `project_id NULL` se ignoran a propósito

## 6. Decisiones sobre el diagrama — botones y feedback visual

Las decisiones sobre un diagrama se toman **únicamente en el chat**, cuando se le muestra el diagrama al usuario. El panel Historial es de solo lectura: consulta versiones y su estado, pero no permite decidir.

| Lugar | Aprobar | Solicitar cambios | Rechazar |
|---|---|---|---|
| Burbuja del chat | sí | sí | sí |
| Panel Historial | no (solo lectura) | no (solo lectura) | no (solo lectura) |

La decisión se guarda **por diagrama** (migración 0017): sobrevive a un F5 y un diagrama ya decidido no vuelve a ofrecer los botones.

### 6.1 Burbuja del chat

- [ ] Con un diagrama recién generado: aparecen "Aprobar", "Rechazar", "Solicitar cambios"
- [ ] Aprobar → "Diagrama aprobado." en verde, botones desaparecen, se manda "Apruebo el diagrama, continuemos." al chat
- [ ] Rechazar → "Diagrama rechazado." en verde, botones desaparecen. A diferencia de Aprobar/Solicitar cambios, no manda ningún mensaje al chat (decisión de diseño: rechazar corta el flujo, no pide otra iteración) — si el criterio de aceptación esperaba que sí avisara al agente, es una línea de código a agregar, avisar si hace falta
- [ ] Solicitar cambios → abre textarea; vacío y "Enviar ajuste" → error "Describe el cambio..."; con texto → se manda el prompt completo al agente, pero la burbuja del usuario muestra solo el feedback escrito **y ahora eso persiste** (ver sección 6.3 — ya no se pierde en un refresh, a diferencia de la ronda anterior)
- [ ] **Persistencia (fix de esta ronda)**: con un diagrama recién generado, presionar **Rechazar** → "Diagrama rechazado." en verde y sin botones → **F5** → el diagrama sigue mostrando "Diagrama rechazado." y **no** vuelven a aparecer los botones. Repetir con **Aprobar** ("Diagrama aprobado.") y con **Solicitar cambios** ("Se registró tu solicitud de cambios."). Cada diagrama tiene su estado propio: uno decidido no afecta a otro diagrama del mismo chat
- [ ] Decidir dos veces el mismo diagrama no es posible desde la UI (no hay botones). Por API: en Swagger, `POST /api/diagrams/decision?project_id=<id>` con `{"decision":"reject","attachment_id":"<id del adjunto>"}` sobre un diagrama ya decidido → **409** `Este diagrama ya tiene una decisión registrada.`; con un `attachment_id` inexistente o de otro proyecto/usuario → **404**. El `id` del adjunto sale de `GET /api/chat/history` o de `GET /api/diagrams/history`
- [ ] Simular error: parar `backend` (`docker compose stop backend`) y hacer click en cualquiera de los tres → mensaje rojo de error, no una falsa confirmación, y los botones siguen visibles. Levantar backend de nuevo (`docker compose start backend`; esperá a ver `Uvicorn running` en `docker compose logs backend`: ahora al arrancar corre primero `init_db` + migraciones)
- [ ] Verificar en DB que la decisión quedó ligada al diagrama:
  ```powershell
  docker compose exec postgres-app psql -U asistente -d asistente_db -c "select id, attachment_id, decision, feedback from approvals where phase='diagram' order by id desc limit 3;"
  ```
  → `decision` en `approved` / `rejected` / `modified` y `attachment_id` con el UUID del diagrama

### 6.2 Panel Historial de diagramas (solo lectura)

- [ ] Abrir el panel → **no** hay botones Aprobar / Pedir cambios / Rechazar ni textarea de feedback (antes había un bloque "¿Qué hacemos con el diagrama actual?"; se eliminó a propósito). Solo queda el botón ✕ para cerrar
- [ ] Cada versión muestra una etiqueta de estado: `✅ Aprobado`, `❌ Rechazado`, `✏️ Cambios solicitados` o `Sin decisión`
- [ ] Rechazar un diagrama en el chat → abrir el panel → esa versión dice `❌ Rechazado` y las demás siguen como estaban
- [ ] Aprobar un diagrama en el chat → abrir el panel → no hay forma de rechazarlo desde ahí (era el bug: se podía aprobar en el chat y rechazar en el historial)
- [ ] Con al menos una versión, el panel muestra al pie la nota "Aquí solo se consulta el historial. Las decisiones sobre un diagrama se toman en el chat, cuando se te muestra."

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
- [ ] Generar 2-3 diagramas → listados del más reciente al más antiguo, cada uno con su etiqueta de estado (ver 6.2)
- [ ] Cerrar y reabrir el panel después de 5+ min → las imágenes siguen cargando (URL re-firmada)
- [ ] Nuevo: proyecto ajeno o backend caído al abrir el panel → mensaje de error en rojo, distinto del texto gris de "no hay diagramas" (antes ambos casos se veían idénticos porque `fetchDiagramHistory` tragaba cualquier error)
- [ ] Con el token del usuario B (Authorize en Swagger), `GET /api/diagrams/history?project_id=<id de un proyecto del usuario A>` → 404
- [ ] En Swagger, `GET /api/diagrams/history` muestra el esquema de respuesta `DiagramHistoryOut` (`diagrams[]` con `message_id`, `id`, `url`, `filename`, `created_at`, `decision`); `decision` es `null` mientras no se decida

## 8. Rate limit y timeouts de Puppeteer

- [ ] Superar `PUPPETEER_RENDER_RATE_LIMIT_PER_MINUTE` en menos de un minuto → falla controlada, backend sigue de pie. Para no pedir 6 diagramas: poné `PUPPETEER_RENDER_RATE_LIMIT_PER_MINUTE=1` en `.env`, `docker compose up -d backend` y pedí dos diagramas en menos de un minuto → el segundo sale sin imagen con `event: degraded`, `reason: puppeteer_rate_limited`. Restaurá el valor después y revisá `docker compose exec backend printenv DATABASE_URL` (aviso de comillas en la sección 10)
- [ ] Respuesta lenta de `puppeteer-mcp` → cae a "sin diagrama" después de ~15s en vez de colgar el chat. Una forma de simularlo: `docker compose pause puppeteer-mcp`, pedir un diagrama y, al terminar, `docker compose unpause puppeteer-mcp`

## 9. Regresión rápida del resto del chat

- [ ] Mensaje que no pide diagrama → responde normal, sin llamadas a Puppeteer
- [ ] Historial de chat viejo (sin columna `attachments` ni `display_content`) sigue cargando; los adjuntos viejos llegan con `decision: null` y muestran los botones (ver sección 10)
- [ ] Elicitación de requerimientos (`/elicitation/message`, `/elicitation/decision`, `/advance`) sigue funcionando sin que el snapshot de propuesta (sección 5) la pise
- [ ] RAG con documentos subidos sigue citando fuentes
- [ ] `POST /api/chat` sin `display_message` en el body (un cliente viejo, o `curl` manual) sigue funcionando igual que siempre — el campo es opcional, `None` por default

## 10. Limitaciones y pendientes conocidos (no reportar como bug nuevo)

- Rechazar en la burbuja no manda mensaje al agente (a propósito, ver 6.1) — confirmar si el criterio de aceptación lo requiere.
- ~~`approvals` no está atado a `project_id`~~ — resuelto con la migración 0016 (ver sección 5, aislamiento). Lo que quede de ese riesgo en `elicitation.py` no se revisó en esta ronda.
- Los diagramas decididos **antes** de la migración 0017 no tienen `attachment_id` (la decisión vieja no decía a qué diagrama se refería), así que vuelven a mostrar los botones una vez y en el historial figuran como `Sin decisión`. No hay forma de recuperarlas.
- Una segunda decisión sobre el mismo diagrama da 409 a propósito (por si se decide desde otra pestaña o llamando a la API directo). Decisiones sin `attachment_id` (clientes viejos) se siguen registrando a nivel de proyecto y no se recuerdan por diagrama.
- **Actualizado**: `app/api/diagrams.py` (`tests/api/test_diagrams.py`), `app/api/proposals.py` (`tests/api/test_proposals.py`) y el sanitizador de Mermaid (`tests/core/test_mermaid_validator.py`) ya tienen tests automáticos — este punto había quedado desactualizado en una ronda anterior. Lo que sigue siendo manual de las secciones 2, 5, 6.1 y 6.2 es sobre todo la parte de UI/UX (botones, mensajes de confirmación en frontend), no la lógica de backend.
- Test `client.test.ts > redirects to /login on 401` es flaky (falla también sin nuestros cambios, confirmado con `git stash`) — no relacionado a HU6.
- Ruido esperado en los logs (no reportar):
  - `Failed to export span batch code: 401` — Langfuse rechaza las claves; el `.env` trae claves que no existen en la DB de Langfuse (típico tras `docker compose down -v`). Solo afecta el tracing.
  - `Context7 unavailable ...; falling back to RAG-only` — el texto dice Context7 aunque la causa sea otra; el motivo real está en `source` y `reason` del payload. `tool_calls_missing` significa que el modelo (por ejemplo `gpt-oss-*`) no llamó a ninguna herramienta; el chat sigue funcionando en modo RAG.
  - `LangChainDeprecationWarning` y `unauthenticated requests to the HF Hub` — inofensivos.
- La detección de nodos no respaldados (grounding) es una heurística de mejor esfuerzo: acepta un nodo si todas sus palabras distintivas están en el contexto, así que `Base de Datos PostgreSQL` pasa si la propuesta menciona PostgreSQL aunque sea de pasada.
- Si el `.env` tiene valores entre comillas simples y algún servicio se recrea (aunque sea en cascada, sin que lo pidas explícitamente), `backend` puede levantar con credenciales de Postgres literalmente entre comillas y todo el login/chat empieza a dar 500. Revisar `docker compose exec backend printenv DATABASE_URL` ante cualquier 500 repentino después de un `up`/`restart`.
- **Corregido** (el fix ya estaba aplicado en el código — `agent.py:175`, `cleaned = cleaned.replace("#quot;", '"')` dentro de `_add` — pero esta guía seguía diciendo "no aplicado todavía" y no había test que lo cubriera): la advertencia de grounding (sección 4) ya no muestra `#quot;` literal cuando el label del nodo trae comillas incrustadas. Se agregó `tests/core/test_agent.py::test_extract_mermaid_node_names_unescapes_quot_entity` como regresión.

## 11. Tests automáticos (migración 0015 / display_content, fixes de render y decisión por diagrama)

Cobertura nueva, para que QA sepa qué ya corre en CI y qué sigue siendo manual:

| Archivo | Qué cubre |
|---|---|
| `tests/core/test_message_store.py::TestDisplayContentColumn` | `save_message(..., display_content=...)` guarda y devuelve el valor; `_coerce_display_content` normaliza `None`/vacío/whitespace a `None` y descarta valores no-string; un mensaje con `display_content` no afecta a los demás en `list_recent` |
| `tests/api/test_chat.py::TestChatRequestDisplayMessage` | El modelo `ChatRequest` acepta `display_message` opcional, default `None` |
| `tests/api/test_chat.py::test_chat_stream_persists_display_message_only_on_user_row` | Integración end-to-end del POST `/api/chat`: `display_message` se persiste en la fila `role="user"`, nunca en la de `role="assistant"` (requiere Postgres de test levantado, igual que el resto de `test_chat.py`) |
| `tests/api/test_chat.py::test_chat_stream_display_message_omitted_keeps_display_content_none` | Caso mayoritario (sin `display_message`): `display_content` queda `None`, sin regresión |
| `tests/api/test_chat_history.py::TestChatHistoryDisplayContent` | `GET /api/chat/history` devuelve `display_content or content`; filas pre-migración (sin `display_content` seteado) no se rompen |
| `tests/api/test_chat_history.py::TestChatHistoryDiagramDecision` | Cada adjunto trae `id` y `decision` (`null` si no se decidió; `approve` / `reject` / `modify` según lo guardado); no se filtra `storage_path`; una decisión de otro proyecto no se devuelve |
| `tests/api/test_diagrams.py::TestPerDiagramDecision` | La decisión se guarda por diagrama y el historial la devuelve; decidir un diagrama no marca a los otros; segunda decisión → 409 y no se persiste; `attachment_id` inexistente / de otro proyecto / de otro usuario → 404; sin `attachment_id` sigue funcionando (compatibilidad) |
| `frontend/.../MessageBubble.test.tsx` (`decision persistida del diagrama`) | Con `decision` en el adjunto (tras un F5) no se ofrecen los botones y se muestra el texto de la decisión; rechazar / aprobar mandan el `attachment_id`; si el backend falla se muestra el error y los botones siguen; dos diagramas en la misma burbuja tienen estado independiente |
| `frontend/.../DiagramHistoryPanel.test.tsx` | El panel es de solo lectura (sin Aprobar / Rechazar / Pedir cambios ni textarea), muestra la etiqueta de estado de cada versión y distingue el error de carga de la lista vacía |
| `frontend/.../api/chat.test.ts` | `_normaliseHistoryAttachments` conserva `id` y `decision` |
| `tests/core/test_agent.py` (grounding) | `find_ungrounded_mermaid_nodes` no marca `Base de Datos PostgreSQL` cuando la propuesta dice `PostgreSQL`, y sigue marcando `Servicio de Blockchain`, `Base de Datos MongoDB`, `Servicio de Pagos Externos` y `Cache Redis` |
| `tests/core/test_agent.py` (render) | El HTML de preview referencia mermaid.js por URL y no lo embebe; el data URL queda bajo el límite de 100 KB del gateway; `_describe_exception` aplana un `ExceptionGroup` para loguear la causa real |
| `tests/api/test_chat.py::test_load_approved_proposal_doc_*` | Ancla de la propuesta aprobada y preferencia por el snapshot guardado. Los mocks de `Approval` deben traer `decision="approved"` |

Correrlos **en tu máquina** (con el venv activo), no dentro de los contenedores: la imagen del backend excluye `tests/` (`.dockerignore`) y `spa` es solo nginx, sin `npm`:
```powershell
# Backend
pytest tests/core/test_message_store.py tests/api/test_chat.py tests/api/test_chat_history.py tests/api/test_diagrams.py tests/api/test_proposals.py tests/core/test_agent.py -v

# Frontend
cd frontend
npm ci
npm run test:run
```

Resultado esperado en frontend: todo en verde salvo el flaky `client.test.ts > redirects to /login on 401` (sección 10). El test de `MessageBubble` "sends the previous Mermaid source when requesting diagram changes" fallaba antes de esta ronda (no pasaba `projectId` y no esperaba el POST asíncrono); ya está corregido.

Los tests de `tests/api/test_chat.py` (igual que el resto del archivo, no es algo nuevo de esta ronda) necesitan la Postgres de test levantada — si corrés pytest fuera de Docker sin esa DB a mano, vas a ver errores de conexión que no tienen nada que ver con el código nuevo.

---

### Qué reportar en cada bug

Paso exacto, resultado esperado vs. obtenido, `project_id` y usuario usado, y el payload del evento SSE relevante (`diagram_validated` / `degraded` / `attachment`) o la respuesta HTTP, copiada de la consola/Network/Swagger.