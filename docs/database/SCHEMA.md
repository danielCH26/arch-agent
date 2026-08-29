# Schema de Base de Datos

> **Issue:** #2 - [F02] Arquitectura técnica del sistema
> **Responsable:** Daniel + Laura
> **Motor:** PostgreSQL 16 + PGVector (imagen: `pgvector/pgvector:pg16`)

---

## Resumen

El sistema utiliza **8 tablas** en PostgreSQL + PGVector:

| Tipo | Tabla | Propósito |
|------|-------|-----------|
| Relacional | `users` | Usuarios y configuración LLM |
| Relacional | `projects` | Proyectos del usuario |
| Relacional | `sessions` | Sesiones de trabajo |
| Relacional | `interaction_logs` | Log de llamadas al LLM (fallback de Langfuse) |
| Relacional | `approvals` | Decisiones de aprobación del usuario |
| Relacional | `uploaded_documents` | Metadata de docs subidos |
| Vectorial | `architect_patterns` | Patrones de arquitectura (seed) |
| Vectorial | `document_chunks` | Chunks de documentos del usuario |

**Dimensión de vectores:** 384 (multilingual-e5-small)

---

## Diagrama ER

```
┌──────────────┐       ┌──────────────┐
│    users     │       │  projects    │
│──────────────│       │──────────────│
│ id (PK)      │──┐    │ id (PK)      │
│ username     │  │    │ user_id (FK) │──┘
│ email        │  │    │ name         │
│ password_hash│  │    │ description  │
│ llm_base_url │  │    │ status       │
│ llm_model    │  │    │ current_phase│
│ encr_api_key │  │    └──────┬───────┘
└──────┬───────┘  │           │
       │          │           │
       │          └───────────┤
       │                      ▼
       │              ┌──────────────┐
       │              │   sessions   │
       │              │──────────────│
       │              │ id (PK)      │
       │              │ project_id FK│
       │              │ phase        │
       │              │ status       │
       │              │ context_data │
       │              │ decisions    │
       │              └──────┬───────┘
       │                     │
       │        ┌────────────┼────────────┐
       │        ▼            ▼            ▼
       │ ┌──────────┐ ┌──────────┐ ┌──────────────┐
       │ │interact. │ │approvals │ │uploaded_docs │
       │ │  _logs   │ │          │ │              │
       │ │──────────│ │──────────│ │──────────────│
       │ │ id (PK)  │ │ id (PK)  │ │ id (PK)      │
       │ │ session  │ │ session  │ │ user_id (FK) │◄──┐
       │ │ _id (FK) │ │ _id (FK) │ │ filename     │   │
       │ │ prompt   │ │ phase    │ │ file_type    │   │
       │ │ response │ │ decision │ │ chunk_count  │   │
       │ │ model    │ │ feedback │ │ processed    │   │
       │ │ tokens   │ │ prev_out │ └──────┬───────┘   │
       │ │ latency  │ │ regen_out│        │           │
       │ └──────────┘ └──────────┘        ▼           │
       │                          ┌──────────────┐     │
       │                          │document_chunks│     │
       │                          │──────────────│     │
       │                          │ id (PK)      │     │
       │                          │ document_id FK│────┘
       │                          │ chunk_text   │
       │                          │ chunk_index  │
       │                          │ embedding VEC│
       │                          │ metadata     │
       │                          └──────────────┘
       │
       ▼
┌────────────────────┐
│ architect_patterns │  (no FK con users, es seed global)
│────────────────────│
│ id (PK)            │
│ pattern_name       │
│ category           │
│ description        │
│ use_cases          │
│ tradeoffs (JSONB)  │
│ embedding VECTOR   │
└────────────────────┘
```

---

## Detalle de cada tabla

### users

Almacena usuarios del sistema y su configuración de LLM.

```sql
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(100) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    llm_base_url VARCHAR(500),         -- configurable por usuario
    llm_model VARCHAR(100),            -- modelo elegido
    encrypted_api_key TEXT,            -- API key encriptada
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);
```

**Decisiones de diseño:**
- `password_hash`: bcrypt o argon2, nunca plaintext
- `encrypted_api_key`: encriptada con clave del servidor (HU12)
- `llm_base_url`: usuario puede usar OpenAI, Ollama, LM Studio, etc.

### projects

Cada proyecto es una iniciativa de diseño de arquitectura.

```sql
CREATE TABLE projects (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    status VARCHAR(50) DEFAULT 'active',  -- active, completed, archived
    current_phase VARCHAR(50),            -- elicitation, proposal, refinement, review
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);
```

**Estados posibles:** `active`, `completed`, `archived`

### sessions

Cada sesión de trabajo del agente para un proyecto.

```sql
CREATE TABLE sessions (
    id SERIAL PRIMARY KEY,
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    phase VARCHAR(50) NOT NULL,    -- elicitation | proposal | refinement | review
    status VARCHAR(50) DEFAULT 'in_progress',
    context_data JSONB,             -- estado actual del agente
    decisions JSONB,                -- decisiones tomadas
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);
```

**JSONB** permite flexibilidad sin migraciones constantes.

### interaction_logs (fallback de Langfuse)

Log de cada llamada al LLM. Funciona como **fallback** si Langfuse falla.

```sql
CREATE TABLE interaction_logs (
    id SERIAL PRIMARY KEY,
    session_id INTEGER REFERENCES sessions(id) ON DELETE CASCADE,
    phase VARCHAR(50),
    prompt TEXT,
    response TEXT,
    model VARCHAR(100),
    tokens_used INTEGER,
    latency_ms INTEGER,
    created_at TIMESTAMP
);
```

### approvals (HU10, HU11)

Cada decisión del usuario sobre una propuesta del agente.

```sql
CREATE TABLE approvals (
    id SERIAL PRIMARY KEY,
    session_id INTEGER REFERENCES sessions(id) ON DELETE CASCADE,
    phase VARCHAR(50) NOT NULL,
    decision VARCHAR(20) NOT NULL,  -- approved | modified | rejected
    feedback TEXT,
    previous_output JSONB,
    regenerated_output JSONB,
    created_at TIMESTAMP,
    CONSTRAINT chk_decision CHECK (decision IN ('approved', 'modified', 'rejected'))
);
```

**CHECK constraint** garantiza valores válidos.

### uploaded_documents (HU13)

Metadata de archivos PDF/MD subidos por el usuario.

```sql
CREATE TABLE uploaded_documents (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    filename VARCHAR(500) NOT NULL,
    file_type VARCHAR(20),           -- pdf, md
    chunk_count INTEGER,
    processed BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP
);
```

### architect_patterns (vectorial, seed)

Patrones de arquitectura precargados. Sin FK porque es seed global.

```sql
CREATE TABLE architect_patterns (
    id SERIAL PRIMARY KEY,
    pattern_name VARCHAR(255) NOT NULL,
    category VARCHAR(100),          -- microservices, monolith, serverless, etc.
    description TEXT,
    use_cases TEXT,
    tradeoffs JSONB,
    embedding vector(384),          -- multilingual-e5-small
    created_at TIMESTAMP
);

CREATE INDEX idx_architect_patterns_embedding
    ON architect_patterns USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);
```

**IVFFLAT con lists=100**: optimizado para ~50-1000 patrones. Si crece, ajustar.

### document_chunks (vectorial, por documento)

Chunks de documentos subidos por usuarios (HU13).

```sql
CREATE TABLE document_chunks (
    id SERIAL PRIMARY KEY,
    document_id INTEGER REFERENCES uploaded_documents(id) ON DELETE CASCADE,
    chunk_text TEXT,
    chunk_index INTEGER,            -- posición en el documento
    embedding vector(384),
    metadata JSONB,                 -- source page, etc.
    created_at TIMESTAMP
);

CREATE INDEX idx_document_chunks_embedding
    ON document_chunks USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);
```

---

## Decisiones de diseño

### ¿Por qué JSONB para campos flexibles?

`context_data`, `decisions`, `tradeoffs`, `previous_output`, `regenerated_output` se almacenan como JSONB porque:

1. Su estructura varía según la fase y el contexto
2. No queremos hacer migraciones cada vez que agregamos un campo
3. PG permite índices y queries sobre JSONB si los necesitamos

### ¿Por qué `vector(384)`?

Corresponde a la dimensión de salida de `multilingual-e5-small`. Si migramos a otro modelo (ej: e5-base de 768d), hay que:
1. Cambiar el tipo de columna
2. Re-indexar todos los embeddings existentes

### ¿Por qué IVFFLAT y no HNSW?

IVFFLAT es el índice por defecto de PGVector y funciona bien para nuestro volumen:
- Hasta ~100k vectores: IVFFLAT es suficiente
- >100k vectores: considerar HNSW (más rápido pero más memoria)

### ¿Por qué `ON DELETE CASCADE`?

Si el usuario borra su cuenta, no queremos dejar sesiones, proyectos, logs huérfanos.
- `users` → `projects`, `uploaded_documents`: CASCADE
- `projects` → `sessions`: CASCADE
- `sessions` → `interaction_logs`, `approvals`: CASCADE
- `uploaded_documents` → `document_chunks`: CASCADE

---

## Inicialización

```bash
# Aplicar el schema
docker compose exec postgres-app psql -U asistente -d asistente_db -f /docker-entrypoint-initdb.d/schema.sql

# O ejecutar el script Python
docker compose exec app python scripts/init_db.py
```

---

## Seed de patrones

Los patrones de arquitectura se cargan con `scripts/seed_patterns.py` (a crear en Sprint 2):

```python
# Pseudocódigo
patterns = [
    {"name": "Microservicios", "category": "distributed", ...},
    {"name": "Monolito", "category": "monolithic", ...},
    {"name": "Serverless", "category": "cloud", ...},
    # ... 50+ patrones
]

for p in patterns:
    embedding = embed(f"{p['name']} {p['description']}")
    db.insert(architect_patterns, {**p, embedding})
```

---

## Migraciones

Las migraciones se manejan con **Alembic** (estándar SQLAlchemy):

```bash
# Crear nueva migración
docker compose exec app alembic revision --autogenerate -m "descripcion"

# Aplicar migraciones
docker compose exec app alembic upgrade head

# Revertir última
docker compose exec app alembic downgrade -1
```

---

## Performance esperado

| Operación | Tiempo esperado |
|-----------|-----------------|
| INSERT de patrón con embedding | ~50ms |
| similarity_search k=5 (1000 vectores) | ~10ms |
| similarity_search k=5 (10k vectores) | ~50ms |
| Carga del schema completo | <1 seg |

---

## Próximos pasos

- [ ] Implementar Alembic para migraciones
- [ ] Crear script de seed con 50 patrones
- [ ] Agregar métricas de uso por tabla
- [ ] Optimizar índices cuando crezca el volumen

---

**Mantenedor:** Daniel + Laura
**Última actualización:** 2026-08-23
