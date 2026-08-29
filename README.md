# arch-agent

Asistente IA que guía a equipos de desarrollo en la definición de arquitecturas de software, desde una idea de producto hasta propuestas justificadas con diagramas y trade-offs.

---

## Quickstart

```bash
# 1. Clonar y configurar
git clone https://github.com/danielCH26/arch-agent.git
cd arch-agent
cp .env.example .env

# 2. Levantar el stack Docker completo (Postgres, backend FastAPI, SPA, Engram, Langfuse)
docker compose up -d

# 3. (Opcional) Setup automatizado: genera JWT y ENCRYPTION_KEY, inicializa DB,
# corre migrations, espera al backend
bash scripts/setup-local.sh
```

Cuando el stack esté arriba:

| Servicio | URL |
|----------|-----|
| **Frontend SPA** | http://localhost:5173 |
| **Backend API** (Swagger) | http://127.0.0.1:8000/docs |
| Langfuse (observabilidad) | http://localhost:3000 |
| Postgres | localhost:5432 |
| Engram (memoria) | http://localhost:7439 |

1. Abrí **http://localhost:5173** y registrate con username + email + password
2. Te logueás automáticamente y caés en el dashboard de proyectos
3. Para usar el agente, primero configurá tu LLM: **Settings → LLM Config** (ver sección abajo)

---

## Features

- **Wizard de configuración LLM** — Elige tu proveedor (OpenAI, Ollama, LM Studio, etc.) con filtro de calidad MMLU
- **Elicitación guiada** — Preguntas progresivas para levantar requerimientos
- **Generación de propuesta** — Arquitectura justificada con patrones reconocidos
- **Diagramas Mermaid.js** — Renderizados automáticamente
- **Trade-offs** — Tabla comparativa con criterios
- **Control del usuario** — Aprueba, modifica o rechaza cada propuesta

---

## Arquitectura

**Stack:** Python 3.11 + FastAPI, React 18 + Vite 6 + TypeScript, PostgreSQL + PGVector, LangChain, Docker Compose.

**11 servicios Docker:**

| Servicio | Función | Puerto host |
|----------|---------|-------------|
| `backend` | FastAPI + LangChain RAG + auth JWT | 8000 |
| `spa` | React build + nginx | 5173 |
| `postgres-app` | DB con extensión `vector` | 5432 |
| `engram` + `engram-proxy` | Memoria persistente (HTTP API) | 7439 |
| `langfuse-web` + `langfuse-db` | Observabilidad LLM | 3000 |
| `clickhouse` + `clickhouse-keeper` | Analytics de Langfuse | — |
| `minio` | Storage S3-compatible para Langfuse | — |
| `redis` | Cache de Langfuse | — |

> **Nota sobre Engram:** El puerto externo es **7439** (no 7437). Esto evita chocar con tu engram local de Gentle AI si lo tenés corriendo en :7437.

---

## Configuración de LLM

Cada usuario configura su propio LLM a través de un **wizard obligatorio de 3 pasos** en `Settings → LLM Config`. El sistema soporta cualquier API OpenAI-compatible.

### Wizard de 3 pasos

1. **Base URL** — Pegás la URL del provider (ej: `https://api.openai.com/v1`). El wizard verifica que el endpoint `/models` existe.
2. **API Key** — Pegás tu key. El wizard testea conexión real con Bearer contra `/models`.
3. **Modelo** — Dropdown filtrado por tier MMLU:
   - **Tier 1 (MMLU ≥ 85)**: badge verde "Recomendado", seleccionable.
   - **Tier 2 / sin score (MMLU 60–85 o desconocido)**: badge amber "Sin score conocido", requiere confirmación.
   - **Tier bloqueado (MMLU < 60)**: NO aparece en el dropdown (gpt-3.5-turbo, llama-8b).
   - **Free-text fallback**: botón "Cancelar" en paso 3 revela un input de texto para tipear modelos custom no listados (fine-tunes, etc).

Si ya tenés config guardada, el wizard muestra una **Summary View** con dos botones: "Cambiar modelo" (salta al paso 3 directo) o "Cambiar todo" (vuelve al paso 1).

### Proveedores soportados

Cualquier API que implemente el formato OpenAI Chat Completions:

| Proveedor | URL base |
|-----------|----------|
| OpenAI | `https://api.openai.com/v1` |
| Ollama (local) | `http://host.docker.internal:11434/v1` |
| LM Studio (local) | `http://host.docker.internal:1234/v1` |
| vLLM (self-hosted) | `http://host.docker.internal:8000/v1` |
| OpenRouter | `https://openrouter.ai/api/v1` |
| Groq | `https://api.groq.com/openai/v1` |
| DeepSeek | `https://api.deepseek.com/v1` |
| Together AI | `https://api.together.xyz/v1` |

> **Ollama / LM Studio desde Docker:** usá `host.docker.internal` en vez de `localhost` para que el contenedor `backend` alcance al provider corriendo en el host.

### Modelos recomendados (Tier 1)

Whitelist mantenida en `app/core/llm_model_benchmarks.yaml`:

- **OpenAI:** `gpt-4o`, `gpt-4-turbo`, `o1`, `o3-mini`, `o4-mini`
- **Anthropic:** `claude-3-5-sonnet-latest`, `claude-3-7-sonnet`, `claude-sonnet-4`, `claude-opus-4`
- **Google:** `gemini-2.5-pro`, `gemini-2.0-pro`
- **Meta:** `llama-3.1-405b-instruct`, `llama-3.3-70b-instruct`

Para agregar más modelos, editá el YAML (citación de fuente requerida) y abrí PR.

---

## Variables de entorno

Copiá `.env.example` a `.env`. Las variables marcadas con `*` son obligatorias.

| Variable | Descripción | Ejemplo |
|----------|-------------|---------|
| `* ENCRYPTION_KEY` | Clave Fernet para encriptar API keys de usuarios | (generar con `bash scripts/setup-local.sh` o `python scripts/generate_encryption_key.py`) |
| `* JWT_SECRET_KEY` | Secreto para firmar JWTs | (autogenerado por setup-local.sh) |
| `JWT_ALGORITHM` | Algoritmo JWT | `HS256` (default) |
| `JWT_EXPIRES_MINUTES` | TTL del token | `60` (default) |
| `* DATABASE_URL` | Conexión a PostgreSQL | `postgresql://asistente:asistente@localhost:5432/asistente_db` |
| `LLM_BASE_URL` | Default LLM base URL para usuarios nuevos | `http://host.docker.internal:11434/v1` |
| `LLM_MODEL` | Default LLM model para usuarios nuevos | `llama3` |
| `LANGFUSE_PUBLIC_KEY` | Langfuse public key | `pk-lf-...` |
| `LANGFUSE_SECRET_KEY` | Langfuse secret key | `sk-lf-...` |
| `LANGFUSE_BASE_URL` | URL de Langfuse (interno Docker) | `http://langfuse-web:3000` |
| `ENGRAM_PROJECT` | Prefijo del namespace en Engram | `arch-agent` |
| `ENGRAM_URL` | URL de Engram (desde el host) | `http://localhost:7439` |
| `CONTEXT7_API_KEY` | API key para Context7 MCP | (opcional) |
| `WEB_SEARCH_API_KEY` | API key para Web Search MCP | (opcional) |

> **Nota:** El setup script `bash scripts/setup-local.sh` autocompleta `JWT_SECRET_KEY` y `ENCRYPTION_KEY` si están vacías. No hace falta generarlas a mano.

---

## Testing

```bash
# Levantar venv local (opcional — los tests también corren dentro de Docker)
python3 -m venv .venv
source .venv/bin/activate
pip install pytest pytest-mock pytest-asyncio

# Correr todos los tests Python
pytest

# Con cobertura
pytest --cov=app --cov=app/core

# Solo un archivo
pytest tests/api/test_llm_wizard.py -v

# Solo el classifier (core, sin DB)
pytest tests/core/test_model_classifier.py -v

# Tests del frontend (Vitest)
cd frontend
npm run test:run
```

**Estructura de tests:**

- `tests/core/` — Tests unitarios puros (no DB, no red)
- `tests/api/` — Tests de endpoints REST con httpx mockeado
- `tests/test_*.py` — Tests legacy de componentes varios

---

## Estructura del proyecto

```
arch-agent/
├── backend/                    # Dockerfile del backend (Python 3.11 slim)
├── frontend/                   # React + Vite SPA
│   ├── src/
│   │   ├── api/                # Cliente HTTP (wizard.ts, llm.ts, auth.ts, etc)
│   │   ├── components/         # Componentes UI
│   │   │   └── llm-wizard/    # Step1, Step2, Step3, SummaryView, LLMWizard
│   │   ├── pages/              # LoginPage, ProjectsPage, SettingsPage, etc
│   │   └── stores/             # Zustand (authStore, projectsStore)
│   ├── Dockerfile              # Multi-stage: node build → nginx serve
│   └── nginx.conf              # Proxy /api → backend:8000
├── app/                        # Backend FastAPI
│   ├── api/                    # Endpoints REST (auth, projects, documents, llm_config, chat)
│   ├── core/                   # DB, encryption, JWT, LLM loader/validator/classifier
│   ├── models/                 # SQLAlchemy models (User, Project, UploadedDocument, etc)
│   └── auth/                   # Register, login, validators
├── migrations/                 # SQL migrations numeradas (0001-0004)
├── scripts/                    # init_db.py, generate_encryption_key.py, setup-local.sh
├── tests/                      # Tests pytest
│   ├── core/                   # Unit tests (model_classifier, etc)
│   └── api/                    # Endpoint tests
├── schema.sql                  # Schema inicial (aplicado por init_db.py)
├── server.py                   # FastAPI entrypoint (uvicorn server:app)
├── docker-compose.yml          # Stack completo (11 servicios)
└── .env.example                # Plantilla de variables de entorno
```

---

## Endpoints REST principales

| Método | Path | Auth | Descripción |
|--------|------|------|-------------|
| `POST` | `/api/auth/register` | No | Crear cuenta |
| `POST` | `/api/auth/login` | No | Login → JWT |
| `POST` | `/api/auth/logout` | Sí | Revoca el JWT actual |
| `GET` | `/api/auth/me` | Sí | Info del usuario actual |
| `GET` | `/api/projects` | Sí | Lista proyectos del usuario |
| `POST` | `/api/projects` | Sí | Crear proyecto |
| `GET` | `/api/projects/{id}` | Sí | Detalle de proyecto |
| `GET` | `/api/projects/{id}/phase` | Sí | Fase actual |
| `POST` | `/api/projects/{id}/advance` | Sí | Avanzar de fase |
| `GET` | `/api/documents` | Sí | Lista documentos del proyecto |
| `POST` | `/api/documents` | Sí | Upload PDF/MD |
| `POST` | `/api/chat` (SSE) | Sí | Chat con el agente (streaming) |
| `GET` | `/api/llm/config` | Sí | Config LLM actual (api_key oculta) |
| `POST` | `/api/llm/wizard/step1` | Sí | Wizard paso 1: valida URL |
| `POST` | `/api/llm/wizard/step2` | Sí | Wizard paso 2: valida API key |
| `POST` | `/api/llm/wizard/step3` | Sí | Wizard paso 3: guarda config con tier enforcement |
| `GET` | `/api/llm/wizard/available-models` | Sí | Lista modelos del provider guardado |

`POST /api/llm/config/validate` está **deprecated** (retorna 410 Gone). Usá el wizard.

---

## Contribuir

Cada issue tiene su branch dedicado (`feature/<ID>-<nombre>`) y PR contra `development`. Ver issues en GitHub para tareas abiertas.

**Convenciones:**

- Backend: 1 PR por issue. Squash-merge aceptado para features chicas.
- Frontend: componentes en `frontend/src/components/<dominio>/`. Hooks custom con prefijo `use`.
- Tests obligatorios para cambios de lógica. Smoke test manual antes de pedir review.
- Si tocás Docker o el stack: rebuild y verificar login + wizard end-to-end.

---

## Licencia

Privado. Todos los derechos reservados.