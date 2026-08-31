# Arquitectura Técnica del Sistema

> **Issue:** #2 - [F02] Arquitectura técnica del sistema
> **Responsable:** Daniel (Tech Lead / PO / Agente)
> **Sprint:** 1
> **Estado:** Documento vivo — se actualiza con cada cambio significativo

---

## 1. Vista General (C4 - Nivel 1)

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    USUARIO (Equipo de desarrollo)                        │
│              navegador web → http://localhost:8000                       │
└────────────────────────────┬────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                  SISTEMA: arch-agent                                     │
│                                                                          │
│   ┌─────────────────┐                                                   │
│   │   Chainlit UI   │  (puerto 8000)                                   │
│   │  (interfaz      │                                                   │
│   │   conversacional)│                                                  │
│   └────────┬────────┘                                                   │
│            │                                                             │
│            ▼                                                             │
│   ┌─────────────────────────────────────────────────────────┐         │
│   │          Agente IA (LangChain)                            │         │
│   │  • Elicitación      • Generación de propuesta              │         │
│   │  • Diagrama         • Trade-offs                          │         │
│   └────────┬──────────────────────────────────────────────────┘         │
│            │                                                             │
│   ┌────────┼─────────────────────────────────────────────────────┐     │
│   │  ┌─────▼──────┐  ┌──────────────┐  ┌──────────────────┐   │     │
│   │  │ PostgreSQL │  │    Engram    │  │     Langfuse     │   │     │
│   │  │ + PGVector │  │   (memoria)  │  │ (observabilidad) │   │     │
│   │  └────────────┘  └──────────────┘  └──────────────────┘   │     │
│   │                                                              │     │
│   │  ┌──────────────────────────────────────────────────────┐  │     │
│   │  │  MCPs: Context7 · Engram · Puppeteer · Filesystem    │  │     │
│   │  │        Web Search · Fetch                            │  │     │
│   │  └──────────────────────────────────────────────────────┘  │     │
│   └──────────────────────────────────────────────────────────────┘     │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

**Propósito:** Asistir a equipos de desarrollo en la definición de arquitecturas de software, guiando al usuario desde una idea inicial hasta una propuesta justificada con diagramas y trade-offs.

---

## 2. Diagrama de Componentes (C4 - Nivel 2)

```
┌────────────────────────────────────────────────────────────────────────┐
│                            ARCH-AGENT                                   │
├────────────────────────────────────────────────────────────────────────┤
│                                                                        │
│  ┌─────────────────────────────────────────────────────────────────┐  │
│  │  PRESENTACIÓN (Chainlit)                                          │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌──────────────┐            │  │
│  │  │  Chat UI    │  │  Diagrama   │  │  Aprobación  │            │  │
│  │  │  (msg)      │  │  Mermaid    │  │  Aprueba/    │            │  │
│  │  │             │  │  + render   │  │  Modifica/   │            │  │
│  │  │             │  │             │  │  Rechaza     │            │  │
│  │  └─────────────┘  └─────────────┘  └──────────────┘            │  │
│  └────────────────────────────┬────────────────────────────────────┘  │
│                                │                                        │
│  ┌─────────────────────────────▼───────────────────────────────────┐  │
│  │  APLICACIÓN (Python - LangChain)                                 │  │
│  │  ┌──────────────────────────────────────────────────────────┐   │  │
│  │  │  Agente (create_agent)                                    │   │  │
│  │  │  ┌─────────┐  ┌──────────┐  ┌──────────┐  ┌─────────┐│   │  │
│  │  │  │Elícita- │─►│ Propone  │─►│ Diagrama │─►│ Aprueba ││   │  │
│  │  │  │  ción   │  │ arquitec-│  │ Mermaid  │  │ usuario ││   │  │
│  │  │  │         │  │ tura     │  │          │  │         ││   │  │
│  │  │  └─────────┘  └──────────┘  └──────────┘  └─────────┘│   │  │
│  │  └──────────────────────────────────────────────────────────┘   │  │
│  │                                                                  │  │
│  │  ┌──────────────────────────────────────────────────────────┐   │  │
│  │  │  Capa RAG                                                  │   │  │
│  │  │  ┌────────────┐  ┌────────────┐  ┌────────────┐         │   │  │
│  │  │  │ Embeddings │─►│  PGVector  │─►│ similarity │         │   │  │
│  │  │  │ (e5-small) │  │  (patrones │  │ _search()  │         │   │  │
│  │  │  │            │  │   + docs)  │  │            │         │   │  │
│  │  │  └────────────┘  └────────────┘  └────────────┘         │   │  │
│  │  └──────────────────────────────────────────────────────────┘   │  │
│  │                                                                  │  │
│  │  ┌──────────────────────────────────────────────────────────┐   │  │
│  │  │  Capa MCP (Model Context Protocol)                        │   │  │
│  │  │  Tier 1: Context7 · Engram · Puppeteer                   │   │  │
│  │  │  Tier 2: Filesystem · Web Search · Fetch                  │   │  │
│  │  └──────────────────────────────────────────────────────────┘   │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                                                                        │
│  ┌─────────────────────────────────────────────────────────────────┐  │
│  │  DATOS                                                            │  │
│  │  ┌──────────────────┐  ┌──────────────────┐                    │  │
│  │  │  PostgreSQL 16   │  │     Engram       │                    │  │
│  │  │  + PGVector      │  │  (SQLite + FTS5) │                    │  │
│  │  │  • 8 tablas      │  │  • 19 tools      │                    │  │
│  │  │  • Vector(384)   │  │  • 1 binario     │                    │  │
│  │  └──────────────────┘  └──────────────────┘                    │  │
│  └─────────────────────────────────────────────────────────────────┘  │
│                                                                        │
│  ┌─────────────────────────────────────────────────────────────────┐  │
│  │  OBSERVABILIDAD (Langfuse self-hosted)                            │  │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌─────┐  │  │
│  │  │ Langfuse │ │ Langfuse │ │Clickhouse│ │  Minio   │ │Redis│  │  │
│  │  │   Web    │ │    DB    │ │(analytics│ │ (storage)│ │cache│  │  │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └─────┘  │  │
│  └─────────────────────────────────────────────────────────────────┘  │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Diagrama de Despliegue

```
┌────────────────────────────────────────────────────────────────────┐
│  HOST MÁQUINA                                                      │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │  Docker Compose (8 servicios)                                │ │
│  │                                                              │ │
│  │  ┌─────────────────────┐                                     │ │
│  │  │ app (8000)          │  ◄── navegador del usuario         │ │
│  │  │ • Chainlit          │                                     │ │
│  │  │ • LangChain         │                                     │ │
│  │  │ • Node.js + uv      │                                     │ │
│  │  │                     │                                     │ │
│  │  │ Volúmenes:          │                                     │ │
│  │  │ • app_uploads       │  ◄── Filesystem MCP                │ │
│  │  │ • app_logs          │                                     │ │
│  │  │ • models_cache      │  ◄── embeddings (~470MB)          │ │
│  │  │ • npm_cache         │                                     │ │
│  │  │ • uv_cache          │                                     │ │
│  │  │ • puppeteer_cache   │  ◄── Chromium (~200MB)             │ │
│  │  └────────┬────────────┘                                     │ │
│  │           │                                                   │ │
│  │           ├────► postgres-app (5432)  pgvector/pgvector:pg16 │ │
│  │           │       Vol: pg_app_data                            │ │
│  │           │                                                   │ │
│  │           ├────► engram (stdio)        ghcr.io/.../engram    │ │
│  │           │       Vol: engram_data                             │ │
│  │           │                                                   │ │
│  │           └────► langfuse-web (3000)  langfuse/langfuse:4    │ │
│  │                   │                                           │ │
│  │                   ├─► langfuse-db (Postgres)                  │ │
│  │                   ├─► clickhouse (analytics)                  │ │
│  │                   ├─► minio (S3 storage)                      │ │
│  │                   └─► redis (cache)                           │ │
│  └─────────────────────────────────────────────────────────────┘ │
│                                                                     │
└────────────────────────────────────────────────────────────────────┘
```

---

## 4. Diagrama de Secuencia — Flujo Principal

```
Usuario       Chainlit       Agente        MCPs          PostgreSQL
  │              │              │             │                │
  │── mensaje ──►│              │             │                │
  │              │── invoke ────►             │                │
  │              │              │── search ───►                │
  │              │              │  (Context7) │                │
  │              │              │◄─ docs ──────│                │
  │              │              │             │                │
  │              │              │── similarity_search() ─────►│
  │              │              │◄─ patterns (top-5) ──────────│
  │              │              │             │                │
  │              │              │── mem_save ──►                │
  │              │              │  (Engram)   │                │
  │              │              │             │                │
  │              │              │  [genera propuesta]           │
  │              │              │             │                │
  │              │◄── propuesta ─│             │                │
  │              │  (JSON)       │             │                │
  │◄── render ───│              │             │                │
  │              │              │             │                │
  │── aprueba ───►              │             │                │
  │              │── log ──────►             │                │
  │              │  (Langfuse)  │             │                │
  │              │              │── INSERT ──►                │
  │              │              │  (approvals) │                │
  │              │              │             │                │
  │              │◄── siguiente fase ─│       │                │
```

---

## 5. Diagrama de Flujo de Datos

```
┌─────────────────────────────────────────────────────────────────────┐
│                                                                     │
│   ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐   │
│   │  Usuario │───►│ Chainlit │───►│  Agente  │───►│  MCPs    │   │
│   └──────────┘    └──────────┘    └────┬─────┘    └──────────┘   │
│        ▲                                │                  │       │
│        │                                ▼                  ▼       │
│        │                          ┌──────────┐      ┌──────────┐  │
│        │                          │ Langfuse │      │ Engram   │  │
│        │                          │ (logs)   │      │ (memory) │  │
│        │                          └──────────┘      └──────────┘  │
│        │                                │                          │
│        │                                ▼                          │
│        │                          ┌──────────────┐                │
│        └──────────────────────────│ PostgreSQL  │                │
│           (resultado renderizado)  │ + PGVector  │                │
│                                    └──────────────┘                │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘

Flujos principales:
1. Input:  Usuario → Chainlit → Agente
2. Output: Agente → Chainlit → Usuario
3. Datos:  Agente → PostgreSQL (persist)
4. Cache:  Agente → Engram (memoria)
5. Trazas: Agente → Langfuse (observabilidad)
```

---

## 6. Stack Tecnológico Resumido

| Capa | Tecnología | Versión |
|------|------------|---------|
| Lenguaje | Python | 3.11+ |
| Framework agente | LangChain | 0.3+ |
| UI | Chainlit | latest |
| DB | PostgreSQL + PGVector | 16 |
| ORM | SQLAlchemy | 2.0+ |
| Embeddings | multilingual-e5-small | 384d |
| Document loaders | PyPDF + UnstructuredMarkdown | - |
| Observabilidad | Langfuse | v4 |
| Memoria | Engram | latest |
| Contenedores | Docker Compose | 3.9 |
| MCPs | Context7, Engram, Puppeteer, Filesystem, Web Search, Fetch | - |

Documento detallado: [`STACK_TECNOLOGICO.md`](./STACK_TECNOLOGICO.md) en el repo de planificación.

---

## 7. Servicios Docker (8 totales)

| # | Servicio | Puerto | Imagen | Volumen | Propósito |
|---|----------|--------|--------|---------|-----------|
| 1 | app | 8000 | custom (Dockerfile) | app_uploads, models_cache, npm_cache, uv_cache, puppeteer_cache | Chainlit + LangChain + MCPs stdio |
| 2 | postgres-app | 5432 | pgvector/pgvector:pg16 | pg_app_data | PostgreSQL + PGVector |
| 3 | engram | stdio | ghcr.io/gentleman-programming/engram:latest | engram_data | Memoria persistente |
| 4 | langfuse-web | 3000 | langfuse/langfuse:4 | - | UI de Langfuse |
| 5 | langfuse-db | - | postgres:16 | langfuse_db_data | DB de Langfuse |
| 6 | clickhouse | - | clickhouse/clickhouse-server:24 | langfuse_clickhouse_data | Analytics |
| 7 | minio | - | minio/minio | langfuse_minio_data | S3 storage |
| 8 | redis | - | redis:7 | - | Cache |

---

## 8. Red y Comunicación entre Servicios

```
┌────────────────────────────────────────────────────────────┐
│  Docker Network (bridge)                                   │
│                                                             │
│  app  ◄────────────► postgres-app (DATABASE_URL)            │
│  app  ◄────────────► engram (stdio)                         │
│  app  ◄────────────► langfuse-web (HTTP)                    │
│  app  ──stdin──► MCPs internos (Puppeteer, Filesystem,    │
│                  Fetch via npx/uvx)                        │
│  app  ──http──► Context7, Web Search (externos)           │
│                                                             │
│  langfuse-web ◄────────────► langfuse-db                   │
│  langfuse-web ◄────────────► clickhouse                    │
│  langfuse-web ◄────────────► minio                         │
│  langfuse-web ◄────────────► redis                          │
│                                                             │
└────────────────────────────────────────────────────────────┘
```

---

## 9. Diagrama ER (Base de Datos)

Ver: [`docs/database/SCHEMA.md`](./database/SCHEMA.md)

---

## 10. ADRs (Architecture Decision Records)

| ADR | Título | Estado |
|-----|--------|--------|
| [ADR-001](./adr/001-langchain-framework.md) | LangChain como framework del agente | ✅ Aceptado |
| [ADR-002](./adr/002-postgres-pgvector.md) | PostgreSQL + PGVector | ✅ Aceptado |
| [ADR-003](./adr/003-embeddings-e5.md) | Embeddings multilingual-e5-small | ✅ Aceptado |
| [ADR-004](./adr/004-langfuse.md) | Langfuse self-hosted | ✅ Aceptado |
| [ADR-005](./adr/005-engram-mcp.md) | Engram como MCP de memoria | ✅ Aceptado |
| [ADR-006](./adr/006-chainlit-ui.md) | Chainlit como UI | ✅ Aceptado |
| [ADR-007](./adr/007-six-mcps.md) | Selección de 6 MCPs | ✅ Aceptado |

---

## 11. Configuración y Despliegue

### Variables de entorno (`.env`)

```bash
# Base de datos
DATABASE_URL=postgresql://asistente:asistente@postgres-app:5432/asistente_db

# Langfuse
LANGFUSE_PUBLIC_KEY=pk-lf-xxxxx
LANGFUSE_SECRET_KEY=sk-lf-xxxxx
LANGFUSE_BASE_URL=http://langfuse-web:3000

# Engram
ENGRAM_PROJECT=asistente-arquitectura

# Embeddings
HF_HOME=/app/models_cache
TRANSFORMERS_CACHE=/app/models_cache
SENTENCE_TRANSFORMERS_HOME=/app/models_cache

# MCPs externos (API keys)
CONTEXT7_API_KEY=
WEB_SEARCH_API_KEY=

# LLM (default; el usuario puede override vía UI)
LLM_BASE_URL=http://host.docker.internal:11434/v1
LLM_MODEL=llama3
```

### Levantar el entorno

```bash
# Levantar todos los servicios
docker compose up -d

# Ver logs
docker compose logs -f app

# Inicializar DB (crea extensión vector + tablas + seed)
docker compose exec app python scripts/init_db.py

# Verificar que todo funciona
curl http://localhost:8000/health
```

---

## 12. Seguridad

| Aspecto | Implementación |
|---------|----------------|
| API Keys encriptadas | Columna `encrypted_api_key` en tabla `users` (Postgres) |
| API Keys no se loggean | Masking en logs de Langfuse |
| HTTPS obligatorio | Validación en config de LLM |
| Filesystem MCP aislado | Solo acceso a `/app/uploads` (volumen) |
| Usuario no-root en Docker | Dockerfile usa `appuser` (uid 1000) |
| Sin acceso a `/home` del host | No se montan carpetas del host |

---

## 13. Performance

| Métrica | Target | Validación |
|---------|--------|------------|
| Tiempo de propuesta | < 5 min | HU9, F19 |
| Tiempo de respuesta promedio | < 3 min | KR4 Santiago |
| Embeddings de 100 chunks | ~5 seg | Bench local |
| Búsqueda k=5 (10k vectores) | ~50 ms | PGVector con IVFFLAT |
| Cobertura de tests | ≥ 80% | F18 |

---

## 14. ArchitectAgent — Agente LangGraph (F08)

> **Issue:** #12 — F08 Generación propuesta + aprobación

### Propósito

El `ArchitectAgent` es un agente conversacional basado en LangGraph que guía al usuario en la definición de arquitecturas de software. Genera propuestas estructuradas con componentes, tecnologías, patrones y justificación.

### Nodos del Grafo

```
START → retrieve_context → build_prompt → call_llm → format_proposal → END
```

| Nodo | Función |
|------|---------|
| `retrieve_context` | Consulta PGVector (documentos del usuario + `architect_patterns`) |
| `build_prompt` | Compone: System prompt + contexto del proyecto + RAG |
| `call_llm` | Invoca el LLM configurado por el usuario (con retry backoff) |
| `format_proposal` | Parsea la respuesta como propuesta estructurada |

### State (AgentState)

```python
class AgentState(TypedDict):
    messages: Sequence[BaseMessage]       # conversación
    user_id: int
    project_id: Optional[int]
    project_context: str                 # info del proyecto activo
    rag_documents: List[Document]        # resultados del RAG
    response_text: str                   # respuesta completa del LLM
    proposal: Optional[Dict]            # propuesta parseada
```

### SSE Events (Chat Endpoint)

El endpoint `/api/chat` retorna Server-Sent Events:

| Event | Payload | Descripción |
|-------|---------|-------------|
| `token` | `{"content": "..."}` | Chunk de texto del LLM |
| `proposal` | `{"has_proposal": true\|false}` | Al final, indica si se parseó propuesta |
| `done` | `null` | Fin del stream |
| `error` | `{"message": "..."}` | Error (LLM no configurado, etc.) |

### Notas de Implementación

- **R13**: Instancia POR REQUEST (nunca global, nunca singleton)
- **R3**: Retry con backoff (2 intentos, delay 1.5s × 2^n)
- **R12**: `CancelledError` manejado para client disconnect

---

## 15. Tablas proposals y approvals

> **Issue:** #12 — F08

### Diagrama ER

```
┌─────────────────────┐       ┌─────────────────────┐
│     proposals       │       │      approvals      │
├─────────────────────┤       ├─────────────────────┤
│ id (PK)             │       │ id (PK)             │
│ session_id (FK)    │◄──────│ proposal_id (FK)    │
│ phase (String)     │       │ decision (String)   │
│ version (Integer)  │       │ feedback (String)   │
│ content (JSONB)    │       │ previous_content    │
│ status (String)    │       │   (JSONB)           │
│ created_at         │       │ modified_content    │
│ updated_at         │       │   (JSONB)           │
└─────────────────────┘       │ created_at         │
                              └─────────────────────┘
```

### Propuestas (proposals)

| Columna | Tipo | Descripción |
|---------|------|-------------|
| `id` | Integer | PK auto-incremental |
| `session_id` | Integer | FK → `sessions.id` |
| `phase` | String(50) | Fase del agente (ej: "architecture") |
| `version` | Integer | Número de versión (1, 2, 3...) |
| `content` | JSONB | `{title, components, technologies, patterns, rationale, raw_text}` |
| `status` | String(20) | `draft` \| `pending_approval` \| `approved` \| `rejected` |
| `created_at` | TIMESTAMP | Server default now() |
| `updated_at` | TIMESTAMP | Server default now() |

**Constraints:**
- Unique: `(session_id, version)`

### Decisiones (approvals)

| Columna | Tipo | Descripción |
|---------|------|-------------|
| `id` | Integer | PK auto-incremental |
| `proposal_id` | Integer | FK → `proposals.id` (CASCADE) |
| `decision` | String(20) | `approved` \| `modified` \| `rejected` |
| `feedback` | String | Feedback del usuario (para modify/reject) |
| `previous_content` | JSONB | Copia del contenido antes del cambio |
| `modified_content` | JSONB | Nuevo contenido (si aplica) |
| `created_at` | TIMESTAMP | Server default now() |

**Constraints:**
- Check: `decision IN ('approved', 'modified', 'rejected')`

### Flujo de versioning

1. Primera propuesta en sesión → `version=1`, `status=draft`
2. siguiente → `version=max+1`, mantiene anterior
3. Approval modifica status: `approved` / `rejected` / `draft` (para modify)

---

## 16. Endpoints de Propuestas (F08)

| Método | Path | Auth | Descripción |
|--------|------|------|-------------|
| `GET` | `/api/proposals?session_id=X` | Sí | Lista propuestas de una sesión |
| `GET` | `/api/proposals/{id}` | Sí | Detalle de propuesta (propia) |
| `POST` | `/api/proposals/{id}/approve` | Sí | Aprueba la propuesta |
| `POST` | `/api/proposals/{id}/reject` | Sí | Rechaza con feedback |
| `POST` | `/api/proposals/{id}/modify` | Sí | Pide modificación (vuelve a draft) |

### Seguridad (R5)

- Ownership verificado vía `proposal → session → user`
- Retorna **404** (nunca 403) cuando no hay acceso — evita information leak
- 409 Conflict si ya está aprobada/rechazada

---

## 17. Próximos Pasos

Esta arquitectura está **cerrada** en cuanto a decisiones macro. Las próximas
iteraciones refinarán:

1. Implementación concreta de cada servicio (Sprint 1-5)
2. Patrones de arquitectura cargados como seed (`architect_patterns`)
3. Prompts del sistema para cada fase del agente
4. UI/UX detallada en Chainlit

---

**Mantenedor:** Daniel (Tech Lead)
**Última actualización:** 2026-08-31
**Versión:** 1.1
