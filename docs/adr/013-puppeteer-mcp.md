# ADR-013: Puppeteer MCP sidecar + postura de seguridad (F13)

**Fecha:** 2026-09-07
**Estado:** Aceptado (propuesto con F13)
**Decisor:** Daniel
**Issue:** #17 — [F13] Puppeteer MCP integrado
**Proposal:** `openspec/changes/2026-09-07-F13-puppeteer-mcp/proposal.md`
**Spec:** `openspec/specs/puppeteer-mcp-integration/spec.md` + `chat-attachments/spec.md` + `engram-conversation-memory` DELTA-1
**ADRs previos referenciados:** ADR-007 (catálogo de MCPs), ADR-010 (runtime de agentes Context7), ADR-011 (espejo Engram)

## Contexto

Issue #17 pide que el asistente renderice diagramas Mermaid como PNG inline
en el chat, en vez de entregar bloques ```mermaid``` que el usuario tiene
que copiar y renderizar a mano. Para hacerlo bien hace falta:

1. **Un browser embebido** (Chromium) que ejecute `mermaid.min.js` y devuelva
   un PNG con los glyphs y el layout correctos.
2. **Una superficie de herramientas chica** — el LLM solo debe poder pedir
   "renderiza este bloque", no "navega a esta URL" (riesgo de prompt
   injection).
3. **Presupuestos por llamada** — un render colgado o un PNG de 200 MB
   son vectores de denial-of-service del backend.
4. **Un mecanismo de autenticación para los PNG** — `<img src=...>` no
   puede llevar `Authorization`, y servir los archivos "porque están en
   `/app/uploads`" es un leak cross-user.
5. **Persistencia atómica** — el row del assistant y la metadata del
   attachment deben commitear juntos para que un fallo en uno haga
   rollback del otro (REQ-ATT-1).

F12 dejo el camino andado (Postgres = verdad, Engram = espejo
fire-and-forget). F13 reutiliza esa transacción pre-`done` para el row +
attachments (mismo `db.commit()` en `_persist_turn`).

## Opciones consideradas

| Opción | Pros | Contras |
|--------|------|---------|
| **A. stdio in-process** — `@modelcontextprotocol/server-puppeteer` corriendo dentro del contenedor `backend` via stdio | Sin servicio extra; menos infraestructura | Imagen Python pasa de ~500MB a ~1.1GB (Chromium ~200MB + node_modules); un solo proceso CPU-heavy por replica; rate-limit en-proc no escala |
| **B. Sidecar + streamable_http** (elegida) — contenedor Node 20 con Chromium pre-baked, expuesto en `:8931/mcp` | Imagen Python intacta; sidecar escala/reinicia independiente; formato HTTP reusable por F14+ (Filesystem/Fetch/Web Search); warm-on-start evita ~1-2s de cold render | Servicio extra en compose (10 → 10); un puerto adicional en la red Docker |
| **C. Servicio SaaS** (Browserless, RemoteOK) | Cero imagen de Chromium en el host | Datos del usuario salen de la red Docker; costo externo; outage externo mata el feature |

## Decisión

**Elegido: B — Sidecar Node 20 con `@modelcontextprotocol/server-puppeteer`
corriendo sobre `streamable_http` en `:8931/mcp`.**

Decisiones de diseño que viajan con esta elección:

### 1. Transporte y superficie (REQ-PMCP-1, REQ-PMCP-2, SCN-PMCP-3)

- `streamable_http` es el transporte moderno que `langchain-mcp-adapters
  0.3.2` exige (el alias `pre `http` está rechazado por esa versión).
- **Positive allow-list** (`app/core/puppeteer_mcp.py:_PUPPETEER_ALLOWED_TOOLS`)
  filtra exactamente a `{puppeteer_screenshot}` DESPUÉS del `client.get_tools()`.
  `puppeteer_navigate`, `_click`, `_fill`, `_select`, `_hover`,
  `_evaluate`, `_pdf` son descartados antes de llegar al LLM. Un futuro
  release del MCP server que agregue herramientas nuevas **no puede
  filtrarse**: el allow-list es la única fuente de verdad, y un test de
  fixture grabada (`tests/core/test_puppeteer_mcp.py::test_get_puppeteer_tools_allow_list_filters_navigate_etc`)
  assertea el comportamiento sobre los 8 nombres upstream conocidos.

### 2. Presupuestos por llamada (REQ-PMCP-3)

- `asyncio.wait_for(timeout=15.0)` envuelve la llamada a `client.get_tools`
  (`_FETCH_TIMEOUT_SECONDS`); un timeout → `PuppeteerUnavailable(reason="puppeteer_timeout")`.
- 2 MB byte cap (`PUPPETEER_MAX_RENDER_BYTES=2097152`) lo aplica el wrapper
  server-side al consumir el PNG; un render > 2MB →
  `PuppeteerUnavailable(reason="puppeteer_byte_cap")`. Defense-in-depth: el
  wrap evita que un render desbocado inunde la memoria del backend antes
  de llegar al cliente.

### 3. Rate limit per-user (REQ-PMCP-4, SCN-PMCP-6)

- Sliding-window in-memory `_RATE_LIMITER: dict[user_id, list[float]]`,
  default 5 renders / 60s. El check (`_check_rate_limit`) corre **antes**
  del MCP round-trip dentro de `_try_get_puppeteer_tools` — un 6th
  request ve `degraded` sin pagar la latencia del streamable_http.
- **Limitación documentada (R-SPEC-4):** el diccionario vive en el
  proceso del backend; un restart lo limpia, y con replicas horizontales
  cada una lleva su propio contador (un usuario podría llegar a
  `5 × N_replicas` si escalamos). F14 promueve a Redis si llega el
  escalado horizontal — la API `_check_rate_limit(user_id)` está diseñada
  para que el reemplazo sea drop-in.

### 4. Auth de attachment (REQ-ATT-2)

- Tokens firmados con `itsdangerous.URLSafeTimedSerializer` (TTL 5 min).
  Key = `SHA-256(JWT_SECRET_KEY)` (mismo secreto que JWT, derivado
  distinto para no exponer el signing de auth a un leak del signing de
  attachments). Salt = `b"attachment-token"` para que un JWT no pueda ser
  reutilizado como attachment-token ni vice-versa.
- `GET /api/chat/attachments/{id}?token=...`:
  - **401** cuando falta / está expirado / está forjado / el `aid` del
    payload no matchea el `{id}` del path (REQ-ATT-2, SCN-ATT-5).
  - **404** cuando el token verifica pero la fila no pertenece al usuario
    (REQ-ATT-2, SCN-ATT-4). **Nunca 403**, para no filtrar existencia.
  - **No WARNING log en el path 404** (mismo posture que `chat_history`)
    — un WARNING aquí sería un side-channel de "este id existe".
- `_ensure_uploads_dir()` se llama lazy desde el primer hit del route, no
  desde `server.py:lifespan` (que no existe hoy). Mantiene `server.py`
  F13-untouched.

### 5. Persistencia atómica (REQ-ATT-1)

- `_persist_turn` (`app/api/chat.py:232-291` después de F13) sigue
  ejecutándose antes de `event: done`. La diferencia: `save_message(assistant)`
  recibe `attachments=collected_attachments`, y `save_message` los mergea
  en la columna JSONB **dentro del mismo `flush()`**. Un fallo del flush
  rollbackea tanto el row como las entries de attachments — el
  `SQLAlchemyError` que sale del `db.commit()` cae en el mismo `except`
  del route que ya manejaba F12, y emite `event: error` con el mensaje
  existente (`messages store unavailable`).

### 6. Browser lifecycle y recursos

- **Persistent Chromium per sidecar** (single replica): `puppeteer.launch()`
  queda corriendo entre renders, eliminado el ~1-2s de cold launch por
  turno. El entrypoint (`infrastructure/puppeteer-mcp/entrypoint.sh`)
  warmea Chromium una vez al boot (`npx ... --version` durante el build
  del Dockerfile precachea las deps del MCP server).
- `mem_limit: 512m` en `docker-compose.yml:puppeteer-mcp` — Chromium con
  un solo tab de Mermaid consume ~200-300MB; 512MB deja headroom para
  picos sin que un OOM silencioso mate el sidecar.

### 7. Storage (JSONB → tabla)

- F13 guarda attachments como dicts JSONB dentro de `messages.attachments`
  (columna `migrations/0009_add_message_attachments.sql`). Es MVP
  simple: una sola fila con un array, una sola transacción por turno.
- **Cuándo promover a tabla normalizada** (`message_attachments
  (id, message_id, storage_path, mime, bytes, created_at, ...)`):
  - Cuando llegue una política de retención (LRU por edad o por quota).
  - Cuando aparezca deletion-on-demand (GDPR right-to-erase granular).
  - Cuando se sumen más tipos de attachment (PDF, SVG, CSV) que
    justifiquen una tabla con tipos discriminados.
- Hasta entonces, JSONB es el contrato canónico y la columna está
  espejada en `schema.sql` para DBs greenfield (`init_db.py` la crea en
  una sola pasada).

## Consecuencias

### Positivas

- Cumple issue #17 end-to-end: assistant emite Mermaid → SPA renderiza
  PNG inline con URL firmada → `<img>` carga el archivo con cache TTL
  corto.
- Sidecar reutilizable: el patrón `streamable_http` + `MultiServerMCPClient`
  ya está en F11 (Context7) y F12 (engram, vía HTTP directo). F14+
  Filesystem / Fetch / Web Search MCP servers encajan sin re-arquitectura.
- Imagen Python intacta (~500MB) — no se suma Chromium al backend.
- Permite rollout por fases vía `PUPPETEER_RENDER_RATE_LIMIT_PER_MINUTE=0`
  (design §7 Phase-1: cada render es rate-limited → `degraded`, chat
  sigue funcionando) sin code revert.

### Negativas

- Sidecar extra en compose (10 servicios en total, dentro del ceiling
  del 007-six-mcps).
- In-memory rate limiter no escala horizontal (R-SPEC-4 → F14 Redis).
- JSONB storage no soporta retention granular — documented como migration
  path futuro (no deuda oculta).
- Live tests del sidecar (`PUPPETEER_LIVE_TEST=1`) son gated — el CI
  estándar no exercise el browser real, solo el wrapper Python.

## Decisiones NO tomadas en este ADR (deferred)

- **Q-NEW-DOWNLOAD-PNG** — botón "Save" opcional en `MessageBubble.tsx`
  (5 LoC). Spec-deferred; fuera del scope F13.
- **Q-NEW-AUTOSCROLL** — frontend-only, no OpenSpec scope.
- **Horizontal scaling del sidecar** — multi-replica + load-balancer en
  compose. No previsto para F13.
- **Otras herramientas Puppeteer (navigate, evaluate)** — ADR-013 las
  descarta explícitamente vía allow-list. F14 las puede re-abrir si
  aparece un caso de uso sanitizado (HTML estático conocido).

## Uso

```python
# _persist_turn ahora acepta attachments kwarg.
asst_msg = save_message(
    db,
    session_id=session_id,
    project_id=body.project_id,
    user_id=user_id,
    role="assistant",
    content=full_response,
    citations=sources,
    attachments=collected_attachments,  # F13: typed dicts from SSE event:attachment
)
```

```bash
# Compose: levantar el sidecar aparte del backend.
docker compose up -d puppeteer-mcp
curl -sf http://localhost:8931/health  # upstream responde 404 → usamos --spider + exit-0

# Backend ya arranca con PUPPETEER_MCP_URL=http://puppeteer-mcp:8931/mcp
docker compose up -d backend
```

## Referencias

- Issue #17 — [F13] Puppeteer MCP integrado.
- `openspec/changes/2026-09-07-F13-puppeteer-mcp/{explore,proposal,design,tasks}.md`.
- `openspec/specs/puppeteer-mcp-integration/spec.md` (REQ-PMCP-1..5, SCN-PMCP-1..7).
- `openspec/specs/chat-attachments/spec.md` (REQ-ATT-1..3, SCN-ATT-1..6).
- `app/core/context7_mcp.py:1-221` — F11 `MultiServerMCPClient` pattern mirrored.
- `app/core/agent.py:113-115, 190-211, 326-340` — `_try_get_context7_tools` precedent
  mirrored by `_try_get_puppeteer_tools`.
- `app/core/message_store.py:37-50` — `_coerce_citations` precedent mirrored by
  `_coerce_attachments`.
- `app/models/message.py:58-62` — `citations` JSONB precedent mirrored by
  `attachments`.
- `app/api/chat.py:232-267` — `_persist_turn` pre-`done` transaction seam extended.
- `migrations/0009_add_message_attachments.sql` — F13 migration, idempotent.
- `docs/adr/007-six-mcps.md:78` — names the Puppeteer package; F13 implements.
- `docs/adr/010-context7-agent-runtime.md` — F11 `MultiServerMCPClient` runtime precedent.
- `docs/adr/011-engram-conversation-mirror.md` — F12 persistence seam; F13 sits next to it.