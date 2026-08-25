# arch-agent

Asistente IA que guía a equipos de desarrollo en la definición de arquitecturas de software, desde una idea de producto hasta propuestas justificadas con diagramas y trade-offs.

---

## Quickstart

```bash
# 1. Clonar y configurar
git clone https://github.com/danielCH26/arch-agent.git
cd arch-agent
cp .env.example .env

# 2. Generar clave de encriptación para API keys
python scripts/generate_encryption_key.py
# Copiar el output a .env como ENCRYPTION_KEY=...

# 3. Levantar Docker Compose
docker compose up -d

# 4. Instalar deps Python (para desarrollo local)
pip install -r requirements.txt

# 5. Inicializar la base de datos
python scripts/init_db.py

# 6. Correr la app completa (registro + Chainlit)
uvicorn server:app --reload --port 8000
```

La pantalla de registro queda en `http://localhost:8000/register` y el chat de
Chainlit en `http://localhost:8000/chainlit`.

---

## Features

- **Configuración flexible de LLM** — Cada usuario elige su proveedor (OpenAI, Ollama local, etc.)
- **Elicitación guiada** — Preguntas progresivas para levantar requerimientos
- **Generación de propuesta** — Arquitectura justificada con patrones reconocidos
- **Diagramas Mermaid.js** — Renderizados automáticamente
- **Trade-offs** — Tabla comparativa con criterios
- **Control del usuario** — Aprueba, modifica o rechaza cada propuesta

---

## Arquitectura

Stack: Python 3.11+, LangChain, PostgreSQL+PGVector, Chainlit, Docker Compose.

8 servicios Docker: Chainlit app, PostgreSQL+PGVector, Engram (memoria), Langfuse (observabilidad), ClickHouse, MinIO, Redis, Langfuse DB.

---

## Configuración de LLM (HU12)

Cada usuario configura su propio LLM desde la interfaz de Chainlit. El sistema soporta **cualquier API OpenAI-compatible**.

### Setup inicial

1. **Genera la clave de encriptación** (solo una vez al instalar):
   ```bash
   python scripts/generate_encryption_key.py
   ```
   Copia el output a tu `.env`:
   ```bash
   ENCRYPTION_KEY=<clave-generada>
   ```

2. **Inicia la app con `uvicorn server:app --reload --port 8000`** y crea una
   cuenta en `http://localhost:8000/register`.

3. **Completa el formulario de configuración LLM** que aparece automáticamente al primer chat:
   - **URL base** (ej: `https://api.openai.com/v1`)
   - **API Key** (se encripta antes de guardar)
   - **Modelo** (se lista después de validar la conexión)

### Proveedores soportados

Cualquier API que implemente el formato OpenAI Chat Completions:

| Proveedor | URL base |
|-----------|----------|
| OpenAI | `https://api.openai.com/v1` |
| Ollama (local) | `http://localhost:11434/v1` |
| LM Studio (local) | `http://localhost:1234/v1` |
| vLLM (self-hosted) | `http://localhost:8000/v1` |
| OpenRouter | `https://openrouter.ai/api/v1` |
| Groq | `https://api.groq.com/openai/v1` |
| DeepSeek | `https://api.deepseek.com/v1` |
| Together AI | `https://api.together.xyz/v1` |

### Cambiar configuración

Una vez configurado, podés cambiar el LLM en cualquier momento desde el botón **⚙️ Configurar LLM** en el sidebar.

---

## Variables de entorno

Copiá `.env.example` a `.env` y completá:

| Variable | Descripción | Ejemplo |
|----------|-------------|---------|
| `ENCRYPTION_KEY` | Clave Fernet para encriptar API keys | (generar con script) |
| `DATABASE_URL` | Conexión a PostgreSQL | `postgresql://asistente:asistente@postgres-app:5432/asistente_db` |
| `LANGFUSE_PUBLIC_KEY` | Langfuse public key | `pk-lf-...` |
| `LANGFUSE_SECRET_KEY` | Langfuse secret key | `sk-lf-...` |
| `LANGFUSE_BASE_URL` | URL de Langfuse | `http://langfuse-web:3000` |
| `WEB_SEARCH_API_KEY` | API key para Web Search MCP | (opcional) |
| `CONTEXT7_API_KEY` | API key para Context7 MCP | (opcional) |

---

## Testing

```bash
# Correr todos los tests
pytest

# Con cobertura
pytest --cov=app

# Solo un archivo
pytest tests/test_encryption.py -v
```

Última cobertura medida: 41 tests, 100% passing.

---

## Estructura del proyecto

```
arch-agent/
├── app/
│   ├── auth/              # Registro, login, perfil
│   ├── core/              # DB, encryption, LLM validator/loader
│   ├── models/            # SQLAlchemy models
│   └── llm/              # UI Chainlit para config LLM
├── tests/                 # Tests pytest
├── scripts/               # Scripts de utilidad
├── requirements.txt
├── schema.sql
└── docker-compose.yml
```

---

## Contribuir

Ver issues en GitHub para tareas abiertas. Cada issue tiene su branch dedicado (`feature/<ID>-<nombre>`).
