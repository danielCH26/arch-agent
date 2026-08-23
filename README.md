# Asistente de Arquitectura — F01: Docker Compose

Levanta el entorno completo del proyecto con un solo comando: **8 servicios
Docker** coordinados con healthchecks, volúmenes persistentes y variables
de entorno externalizadas en `.env`.

> Issue: [`[F01] Setup Docker Compose (8 servicios)`](https://github.com/danielCH26/arch-agent/issues/1)

---

## Servicios

| #  | Servicio       | Puerto host | Imagen                              | Propósito                       |
|----|----------------|-------------|-------------------------------------|---------------------------------|
| 1  | `app`          | 8000        | build local (Dockerfile)            | Chainlit + LangChain + MCPs     |
| 2  | `postgres-app` | 5432        | `pgvector/pgvector:pg16`            | DB app + vectores (PGVector)    |
| 3  | `engram`       | stdio       | `ghcr.io/gentleman-programming/engram:latest` | Memoria persistente del agente |
| 4  | `langfuse-web` | 3000        | `langfuse/langfuse:4`               | UI de tracing / observabilidad  |
| 5  | `langfuse-db`  | —           | `postgres:16`                       | DB propia de Langfuse           |
| 6  | `clickhouse`   | —           | `clickhouse/clickhouse-server:24`   | Analytics de Langfuse           |
| 7  | `minio`        | —           | `minio/minio:latest`                | Storage S3-compatible           |
| 8  | `redis`        | —           | `redis:7`                           | Cache de Langfuse               |

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
docker compose logs -f app
```

URLs útiles una vez levantado:

| URL                                   | Qué es                          |
|---------------------------------------|---------------------------------|
| http://localhost:8000                 | UI de Chainlit (el agente)      |
| http://localhost:8000/health          | Healthcheck de la app           |
| http://localhost:3000                 | UI de Langfuse (admin/admin123) |
| `postgres-app:5432` desde el host     | DB de la app (vía `localhost:5432`) |

---

## Estructura del repo

```
.
├── docker-compose.yml     # 8 servicios orquestados
├── Dockerfile             # Imagen del servicio `app`
├── .env.example           # Plantilla de variables de entorno
├── .env                   # Variables locales (NO commitear)
├── .gitignore
├── requirements.txt       # Dependencias Python
├── app.py                 # Entrypoint Chainlit (smoke test por ahora)
└── README.md              # Este archivo
```

---

## Comandos utiles

```bash
# Ver estado / salud
docker compose ps
docker compose logs -f app
docker compose logs -f langfuse-web

# Reiniciar un solo servicio
docker compose restart app

# Entrar al container de la app
docker compose exec app bash

# Conectarse a Postgres
docker compose exec postgres-app psql -U asistente -d asistente_db

# Ver stats de Engram
docker compose exec engram engram stats

# Backup de Engram
docker compose exec engram engram export > backups/engram-$(date +%F).json

# Bajar todo (conservando volumenes)
docker compose down

# Bajar todo y BORRAR volumenes (reset completo)
docker compose down -v
```

---

## Criterios de aceptacion (issue F01)

- [x] `docker compose up` levanta los 8 servicios
- [x] Healthchecks configurados en todos los servicios
- [x] Volumenes persistentes para cada servicio con datos
- [x] Variables de entorno externalizadas en `.env`
- [x] Red propia `asistente-net` para aislar el stack
- [x] `restart: unless-stopped` en servicios de estado

---

## Troubleshooting

**`Cannot connect to Docker daemon`**
Docker Desktop no esta corriendo. Abre Docker Desktop y reintenta.

**`port is already allocated`**
Otro proceso usa el puerto. Cambia el mapeo en `docker-compose.yml`
o para el proceso que lo ocupa.

**`langfuse-web` no arranca**
Espera ~30s al primer arranque (migraciones de DB). Verifica con
`docker compose logs -f langfuse-web`.

**Quiero resetear todo desde cero**
```bash
docker compose down -v
docker compose up -d
```

---

## Proximos pasos

- **F02** — Arquitectura tecnica detallada
- **F03** — Seed con caso de ejemplo
- **F04** — Mockups UI
- **F05..F10** — Pipeline RAG y elicitación
