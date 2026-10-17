# CI/CD Pipeline

## Overview

Este documento describe el pipeline de CI/CD de `arch-agent` y cómo interactuar con él. La estrategia tiene dos ejes: **rapidez en PRs de feature** (tests contra un Postgres+pgvector efímero) y **confianza cerca de release** (stack de Docker Compose, build de las imágenes y frontend en PRs a `main`). El deploy a producción está desacoplado del flujo de PRs: mergear a `main` nunca despliega; solo lo hace un tag semver estable (o un re-deploy manual para rollback).

Hay tres workflows en `.github/workflows/`:

- `pr-development.yml`: PRs que no apuntan a `main` y pushes a `development`. Reemplaza al antiguo `ci.yml`.
- `pr-main.yml`: PRs contra `main`.
- `deploy-railway.yml`: tags `vX.Y.Z` y re-deploys manuales.

OpenSpec sigue siendo la fuente de verdad para cambios de comportamiento.

## Branch Flow

| Evento | Workflow | Checks (job names) | Qué corre |
|--------|----------|--------------------|-----------|
| PR contra `development` o PR encadenado (base = otra rama de feature) | `pr-development.yml` | `dev-backend-tests`, `dev-frontend-tests` | Backend: service container `pgvector/pgvector:pg16`, `scripts/init_db.py` + `migrations.run_migrations`, `pytest`. Frontend: `npm ci`, `vitest run`, `npm run build` (tsc + vite) |
| Push a `development` (merge de un PR) | `pr-development.yml` | los mismos | Lo mismo, para que `development` siempre tenga una corrida verde |
| PR contra `main` | `pr-main.yml` | `main-backend-tests`, `main-frontend-tests`, `main-docker-build` | Backend: `docker compose up --wait` de `postgres-app`, `engram`, `engram-proxy` y `langfuse-web` (+ sus dependencias), probe HTTP de Engram y Langfuse, schema + migraciones sobre `postgres-app`, `pytest`, smoke import `from server import app`. Frontend: igual que en development. Docker: build de `backend/Dockerfile` y `frontend/Dockerfile` (sin push) |
| Push de tag `vX.Y.Z` | `deploy-railway.yml` | `deploy` | Verifica que el commit esté en `main`, espera la aprobación del environment `production` y corre `railway up --ci --service $RAILWAY_SERVICE` |
| Manual (`workflow_dispatch`, input `ref`) | `deploy-railway.yml` | `deploy` | Igual que el tag, con el `ref` elegido. Es el camino de rollback |

Los workflows de PR cancelan la corrida anterior de la misma rama al pushear (`concurrency`), tienen `timeout-minutes` y `permissions: contents: read`.

### Bases de datos por lane

Cada lane usa su propio Postgres y no comparten datos:

| Lane | Postgres | `DATABASE_URL` |
|------|----------|----------------|
| `pr-development` | service container `pgvector/pgvector:pg16` | `postgresql://test:test@localhost:5432/test` |
| `pr-main` | `postgres-app` de `docker-compose.yml`, credenciales de `.env.example` | `postgresql://asistente:asistente@localhost:5432/asistente_db` |

Los tests **no deben hardcodear** una base. Los conftest (`tests/conftest.py`, `tests/api/conftest.py`) y los módulos de test usan `os.environ.setdefault(...)`, así que el `DATABASE_URL`, `JWT_*` y `ENCRYPTION_KEY` que exporte el workflow (o el developer) llegan intactos a todos los tests; los defaults solo aplican cuando no hay nada exportado.

### Costo del backend

- `torch` se instala primero desde el índice CPU (`PIP_EXTRA_INDEX_URL` + `pip install torch --index-url .../whl/cpu`), igual que `backend/Dockerfile`. Sin eso `sentence-transformers` baja torch con CUDA (varios GB).
- El modelo `multilingual-e5-small` (~470 MB) que descarga un test se cachea en `.hf-cache` con `actions/cache` (`HF_HOME`).
- `EMBEDDINGS_WARMUP=off` evita cargar el modelo al importar la app.

### Lo que `pr-main` no ejercita

Ningún test habla todavía con Engram ni con Langfuse reales (usan mocks). El job levanta esos servicios para validar que `docker-compose.yml` arranca y que responden por HTTP, no para testear integración. Cuando lleguen tests de integración contra Postgres real (#104/#105), ya corren en ambos lanes porque los dos aplican schema + migraciones.

## Visual Diagram

```mermaid
graph LR
    A[feature/*] -->|PR: dev-backend-tests + dev-frontend-tests| B[development]
    B -->|PR: main-backend-tests + main-frontend-tests + main-docker-build| C[main]
    C -->|tag vX.Y.Z + aprobación production| D[Railway]
```

## Secrets y variables

Se configuran en **Settings → Secrets and variables → Actions**. Ningún workflow de PR necesita secrets: todos los valores que usan son de CI y salen de `.env.example` o del propio YAML.

| Nombre | Tipo | Lo usa | Dónde obtenerlo |
|--------|------|--------|-----------------|
| `RAILWAY_TOKEN` | Secret | `deploy-railway.yml` | Token de **proyecto**: Railway → proyecto → Settings → Tokens ([docs](https://docs.railway.com/guides/cli#tokens)), environment `production`. Los tokens de cuenta/workspace (`railway.app/account/tokens`) van en `RAILWAY_API_TOKEN` y **no** sirven para este workflow |
| `RAILWAY_SERVICE` | Variable (no secret) | `deploy-railway.yml` | Nombre del servicio backend en Railway. Sin él `railway up` pregunta a qué servicio desplegar y en CI no hay TTY |

Las claves de Langfuse (`pk-lf-asistente-prod` / `sk-lf-...`) que ve `pr-main` son las de `.env.example`: Langfuse las crea al arrancar vía `LANGFUSE_INIT_*`, solo existen en esa instancia efímera y no son secrets. Las de producción viven en las variables del servicio en Railway, no en GitHub.

## Configuración única de Railway

1. En el servicio backend, agregar la variable `RAILWAY_DOCKERFILE_PATH=backend/Dockerfile`. `railway up` sube el checkout desde la raíz y, sin esto, Railway autodetecta el build en lugar de usar el Dockerfile.
2. **No** conectar el repo de GitHub al servicio (o, si ya está, desconectarlo en Service → Settings → Source). Conectado, Railway auto-despliega cada push a la rama enlazada y rompe la regla de "merge a main no despliega". `railway up` no necesita el enlace.
3. En GitHub, crear el environment `production` (Settings → Environments) con required reviewers. El job de deploy queda en espera hasta que alguien lo apruebe.
4. Cargar `RAILWAY_TOKEN` y `RAILWAY_SERVICE` como se indica arriba.

La versión del CLI está fijada en `RAILWAY_CLI_VERSION` dentro del workflow. Para subirla, probarla primero con un re-deploy manual.

## How to cut a release

```bash
# 1. Estar en main, actualizado y con los checks de PR - Main en verde
git checkout main
git pull --ff-only

# 2. Crear el tag semver estable
git tag v0.1.0

# 3. Pushear SOLO ese tag (dispara deploy-railway.yml)
git push origin v0.1.0

# 4. Aprobar y verificar el deploy
#   - Actions → "Deploy to Railway" → Review deployments → production → Approve
#   - El job usa `railway up --ci`: queda rojo si el build falla
#   - Railway → proyecto → Deployments para ver el rollout
```

Convención de tags: `vMAJOR.MINOR.PATCH`. Solo los estables (`v0.1.0`, `v1.4.2`) disparan el deploy; un pre-release como `v2.0.0-rc.1` no matchea el filtro y no despliega. Un tag sobre un commit que no está en `main` hace fallar el job antes de desplegar.

No usar `git push --tags`: empuja todos los tags locales y puede disparar varios deploys (se encolan por `concurrency`, pero igual despliegan).

## How to roll back

**Opción A — Railway UI (la más rápida):**
1. Railway → proyecto → Deployments.
2. Buscar el último deploy sano → "Redeploy".

**Opción B — Re-deploy de un tag anterior desde GitHub:**
1. Actions → "Deploy to Railway" → Run workflow.
2. En `ref`, poner el tag anterior (por ejemplo `v0.1.2`) → Run, y aprobar el environment.

Sirve para que el historial de Actions refleje qué versión está corriendo. No mueve ni re-crea tags.

**Opción C — Revertir y sacar un tag nuevo:**
```bash
git revert <commit-del-bug>   # vía PR a main, como cualquier cambio
git tag v0.1.4
git push origin v0.1.4
```

## Branch Protection Checklist

El pipeline no aplica estas reglas por sí solo. `scripts/enable-branch-protection.sh` las aplica vía `gh api` (con `DRY_RUN=1` por defecto) y verifica antes que cada check requerido ya tenga una corrida verde. Leer el encabezado del script antes de correrlo: el `PUT` **reemplaza** la protección existente de la rama (guarda un backup antes).

### `development`

- [ ] Require a pull request before merging
- [ ] Require approvals: **0** (es staging, merge rápido)
- [ ] Dismiss stale pull request approvals when new commits are pushed
- [ ] Require status checks to pass before merging
  - [ ] `dev-backend-tests`
  - [ ] `dev-frontend-tests`
  - [ ] Require branches to be up to date: **off** (`strict: false`). Con historia lineal y muchos PRs abiertos, activarlo obliga a rebasear todo cada vez que algo se mergea; los checks corren igual sobre el merge ref del PR
- [ ] Require linear history
- [ ] Do not allow force pushes
- [ ] Do not allow deletions

### `main`

- [ ] Require a pull request before merging
- [ ] Require approvals: **1** mínimo (`MAIN_APPROVALS`)
- [ ] Dismiss stale pull request approvals when new commits are pushed
- [ ] Require status checks to pass before merging
  - [ ] `main-backend-tests`
  - [ ] `main-frontend-tests`
  - [ ] `main-docker-build`
  - [ ] Require branches to be up to date: **off** (mismo motivo)
- [ ] Require linear history
- [ ] Include administrators (`MAIN_ENFORCE_ADMINS=true`). Implica que nadie, tampoco el dueño, mergea a `main` un PR propio sin la aprobación de otra persona
- [ ] Do not allow force pushes
- [ ] Do not allow deletions
- [ ] Allow auto-merge: **off** (review explícito antes de taggear)

### Reglas globales sugeridas

- Default branch: `main`.
- Restringir quién puede crear tags `v*` con un **tag ruleset** (Settings → Rules → Rulesets → New tag ruleset), limitado a maintainers.
