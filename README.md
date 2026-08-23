# arch-agent de Arquitectura — F01: Docker Compose

Levanta el entorno completo del proyecto con un solo comando: **8 servicios
Docker** (más `clickhouse-keeper` como dependencia dura de Langfuse)
coordinados con healthchecks, volúmenes persistentes y variables de
entorno externalizadas en `.env`.

> Issue: [`[F01] Setup Docker Compose (8 servicios)`](https://github.com/danielCH26/arch-agent/issues/1)

> **Scope de F01:** este issue SOLO valida que `docker compose up` levante
> los servicios. La imagen real de `app` (Chainlit + LangChain) llega en F02.
> Aqui `app` es un placeholder (`alpine + sleep infinity`) para mantener el
> spec de 8 servicios.

---

## Servicios

| #  | Servicio              | Puerto host | Imagen                                       | Propósito                                  |
|----|-----------------------|-------------|----------------------------------------------|--------------------------------------------|
| 1  | `app`                 | —           | `alpine:3.19` (placeholder, F02 lo reemplaza) | Chainlit + LangChain + MCPs (en F02)       |
| 2  | `postgres-app`        | 5432        | `pgvector/pgvector:pg16`                     | DB app + vectores (PGVector)               |
| 3  | `engram`              | 7437        | `ghcr.io/gentleman-programming/engram:latest` | Memoria persistente del agente             |
| 4  | `langfuse-web`        | 3000        | `langfuse/langfuse:3`                        | UI de tracing / observabilidad             |
| 5  | `langfuse-db`         | —           | `postgres:16`                                | DB propia de Langfuse                      |
| 6  | `clickhouse`          | —           | `clickhouse/clickhouse-server:24`            | Analytics de Langfuse                      |
| 7  | `minio`               | —           | `minio/minio:latest`                         | Storage S3-compatible                      |
| 8  | `redis`               | —           | `redis:7`                                    | Cache de Langfuse                          |
| —  | `clickhouse-keeper`   | —           | `clickhouse/clickhouse-keeper:24`            | Coordinacion distribuida (ReplicatedMergeTree) |

---

## Quick start

```bash
# 1. Copiar la plantilla de variables de entorno
cp .env.example .env

# 2. Levantar todo en background
docker compose up -d

# 3. Ver el estado de los servicios
docker compose ps

# 4. Ver logs en vivo
docker compose logs -f
```

URLs utiles una vez levantado:

| URL                                   | Que es                              |
|---------------------------------------|-------------------------------------|
| http://localhost:3000                 | UI de Langfuse (admin/admin123)     |
| `localhost:5432`                      | DB de la app (postgres-app)         |

> Nota: Chainlit (puerto 8000) llega en F02. Por ahora `app` solo existe como
> placeholder para mantener el spec.

---

## Configuracion por desarrollador (importante)

**Regla de oro:** el archivo `.env` (con tus secretos) **NUNCA** se commitea al repo.
Cada miembro del equipo genera su propio `.env` a partir de `.env.example`.

### Setup inicial (una vez)

```bash
# 1. Clonar el repo
git clone <repo-url>
cd arch-agent

# 2. Copiar la plantilla
cp .env.example .env          # Mac/Linux
copy .env.example .env        # Windows (cmd.exe)

# 3. Editar .env con TUS credenciales (ver seccion siguiente)
notepad .env                  # o tu editor favorito
```

### Que valores debes cambiar

| Variable | Por que cambiarla | Como obtenerla |
|----------|-------------------|----------------|
| `LANGFUSE_PUBLIC_KEY` | Identifica tu instancia de Langfuse | Se genera sola en Langfuse UI (http://localhost:3000) al primer login |
| `LANGFUSE_SECRET_KEY` | Lo mismo, es la clave privada | Misma UI, Settings -> API Keys |
| `LANGFUSE_SALT` | Usado para encriptar datos en Langfuse | Cualquier string random de 32+ chars (`openssl rand -hex 32`) |
| `NEXTAUTH_SECRET` | Firma los tokens de sesion de Langfuse | Cualquier string random de 32+ chars |
| `LANGFUSE_INIT_USER_PASSWORD` | Tu password personal para Langfuse | El que vos quieras (no uses `admin123` en prod) |
| `POSTGRES_PASSWORD` | Password de tu DB local | Cualquiera, es solo local |
| `MINIO_ROOT_PASSWORD` | Password del storage S3 | Cualquiera, es solo local |
| `REDIS_PASSWORD` | Password del cache | Cualquiera, es solo local |
| `LLM_BASE_URL` | Apunta a tu provider LLM | `http://host.docker.internal:11434/v1` (Ollama), `https://api.openai.com/v1` (OpenAI), etc. |
| `LLM_MODEL` | Que modelo usar | Depende del provider (`llama3`, `gpt-4o-mini`, etc.) |
| `CONTEXT7_API_KEY` | API key de Context7 (opcional) | https://context7.com |
| `WEB_SEARCH_API_KEY` | API key de busqueda web (opcional) | Tavily o Exa |

### Que pasa con el .env

- `.env` esta en `.gitignore` → `git add .` NUNCA lo va a incluir
- Si accidentalmente haces `git add .env`, hace `git rm --cached .env` y commitea el `.gitignore`
- Si ya lo subiste, rotar TODAS las credenciales (asumir comprometo)
- Para trabajo en equipo, cada dev tiene su propio `.env` local

### Verificar que .env no se commitea

```bash
git status
# .env NO debe aparecer en la lista
```

Si aparece, parar y revisar `.gitignore` antes de cualquier `git commit`.

---

## Estructura del repo

```
.
├── docker-compose.yml                  # 8 servicios (+ clickhouse-keeper)
├── .env.example                        # Plantilla de variables de entorno
├── .env                                # Variables locales (NO commitear)
├── .gitignore
├── docker/
│   ├── clickhouse-config.xml           # Cluster 'default' single-node
│   └── clickhouse-keeper-config.xml    # Config del keeper
└── README.md                           # Este archivo
```

---

## Comandos utiles

```bash
# Ver estado / salud
docker compose ps
docker compose logs -f langfuse-web
docker compose logs -f postgres-app

# Reiniciar un solo servicio
docker compose restart langfuse-web

# Conectarse a Postgres
docker compose exec postgres-app psql -U arch-agent -d arch_agent_db

# Bajar todo (conservando volumenes)
docker compose down

# Bajar todo y BORRAR volumenes (reset completo)
docker compose down -v
```

---

## Criterios de aceptacion (issue F01)

- [x] `docker compose up` levanta los servicios del spec
- [x] Healthchecks configurados en los servicios de estado
- [x] Volumenes persistentes para cada servicio con datos
- [x] Variables de entorno externalizadas en `.env`
- [x] Red propia `arch-agent-net` para aislar el stack
- [x] `restart: unless-stopped` en servicios de estado

---

## Troubleshooting

**`Cannot connect to Docker daemon`**
Docker Desktop no esta corriendo. Abre Docker Desktop y reintenta.

**`port is already allocated`**
Otro proceso usa el puerto. Cambia el mapeo en `docker-compose.yml`
o para el proceso que lo ocupa.

**`langfuse-web` tarda en arrancar**
Normal en el primer `up` (migraciones de Prisma + ClickHouse). Espera 60-90s
y revisa con `docker compose logs -f langfuse-web`.

**Quiero resetear todo desde cero**
```bash
docker compose down -v
docker compose up -d
```

---

## Proximos pasos

- **F02** — Arquitectura tecnica detallada + imagen real del `app` (Chainlit + LangChain)
- **F03** — Seed con caso de ejemplo
- **F04** — Mockups UI
- **F05..F10** — Pipeline RAG y elicitación
