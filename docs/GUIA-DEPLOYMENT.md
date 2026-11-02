# Guía de despliegue

Cómo levantar Arch-Agent en local y desplegarlo en producción.

**Tiempo objetivo: menos de 30 minutos** para tener el stack andando desde cero.
Al final está el [checklist](#checklist-del-kr) para medirlo.

- Instalación local → esta página
- Uso de la app (registro, primer proyecto) → [`docs/usuario/01-inicio-rapido.md`](usuario/01-inicio-rapido.md)
- Problemas frecuentes de la app → [`docs/usuario/03-faq.md`](usuario/03-faq.md)
- Pipelines de CI y despliegue a Railway → [`CI-CD.md`](CI-CD.md)

---

## 1. Requisitos

| Qué | Versión | Para qué |
|---|---|---|
| **Docker Desktop** | Compose **v2.24+** | Corre todo el stack. En Windows tiene que estar **corriendo** (icono en la bandeja), no solo instalado |
| **Git** | cualquiera | Clonar el repo |
| RAM | 8 GB libres | El stack levanta 11 servicios; con menos, Postgres compite con Docker y falla |
| Disco | 6 GB libres | Imágenes de Docker + modelos de embeddings (~470 MB) |
| Puertos libres | 3000, 5173, 5432, 7439, 8000 | Los usa el stack (ver [tabla](#servicios-y-puertos)) |

No hace falta **Python** ni **Node** locales: todo corre dentro de Docker.

> **Windows:** `docker compose` (con espacio, sin guion) es Compose v2. Si tenés `docker-compose` con guion, es v1 y **no sirve** para `docker-compose.walk.yml`.

---

## 2. Instalación local

### Opción A — el script (recomendada)

```bash
git clone https://github.com/danielCH26/arch-agent.git
cd arch-agent
bash scripts/setup-local.sh
```

El script es **re-ejecutable**: detecta qué pasos ya hizo y se los salta. Genera `JWT_SECRET_KEY` y `ENCRYPTION_KEY` si están vacías, levanta el stack y espera a que el backend responda.

### Opción B — manual

```bash
git clone https://github.com/danielCH26/arch-agent.git
cd arch-agent
cp .env.example .env

# Genera las dos claves que el backend exige.
# El script imprime un banner: copiá la LÍNEA que empieza con "ENCRYPTION_KEY=".
python scripts/generate_encryption_key.py
# JWT_SECRET_KEY: cualquier string largo y aleatorio

docker compose up -d
```

El backend aplica `schema.sql` y las migraciones pendientes **solo al arrancar** (su `command` es `init_db.py && migrations.run_migrations && uvicorn`). No hace falta correr nada a mano.

**Para levantar de nuevo después de tocar migraciones:**

```bash
docker compose up -d --build backend
docker compose exec -T backend python scripts/seed_patterns.py   # reindexa los patrones
```

### Opción C — solo el backend, sin el resto

Para trabajar sobre la API sin levantar Langfuse, ClickHouse, MinIO ni Redis:

```bash
docker compose up -d postgres-app backend spa
```

La SPA queda en <http://localhost:5173> y la API en <http://127.0.0.1:8000/docs>.

---

## 3. Variables de entorno

`.env.example` tiene 67 variables. **La mayoría ya vienen con un valor por defecto que funciona.** Solo hay que mirar estas:

### Obligatorias (el backend no arranca sin ellas)

| Variable | Qué es | Cómo obtenerla |
|---|---|---|
| `JWT_SECRET_KEY` | Firma los tokens de sesión | Cualquier string aleatorio de 32+ caracteres. El script de setup lo genera |
| `ENCRYPTION_KEY` | Cifra la API key del LLM del usuario | **Fernet**: 32 bytes en base64 url-safe. `python -m scripts.generate_encryption_key` |

> `ENCRYPTION_KEY` no es un string cualquiera: tiene que ser una clave Fernet
> válida (44 caracteres base64 url-safe). Si no lo es, el wizard del LLM
> falla con un **500** al cifrar la API key.

### Para usar un LLM

| Variable | Cuándo |
|---|---|
| *(ninguna)* | Si configurás el LLM **desde la UI** (engranaje → Configuración Global del LLM). Es lo recomendado |
| `GROQ_API_KEY` | Si querés el default de backend (Groq, `openai/gpt-oss-120b`) sin tocar la UI |

### Solo para funciones opcionales

| Variable | Para qué |
|---|---|
| `CONTEXT7_API_KEY` | Documentación de librerías vía Context7 |
| `WEB_SEARCH_API_KEY` | Búsqueda web durante la propuesta |

### Lo que **no** hay que tocar

`POSTGRES_*`, `LANGFUSE_*`, `CLICKHOUSE_*`, `MINIO_*`, `REDIS_PASSWORD`, `ENGRAM_*` ya vienen con valores coherentes entre sí. Cambiarlos a mano es la forma más fácil de romper el stack.

---

## 4. Verificar que anda

### Servicios y puertos

Con el stack arriba, esto tiene que responder:

| Qué | URL | Respuesta esperada |
|---|---|---|
| **Frontend SPA** | <http://localhost:5173> | La pantalla de login |
| **API (Swagger)** | <http://127.0.0.1:8000/docs> | La interfaz de OpenAPI |
| **Langfuse** | <http://localhost:3000> | Login de Langfuse |
| **Engram** | <http://localhost:7439/health> | JSON de estado |

Y después, en el navegador:

1. Registrarse en <http://localhost:5173> (la contraseña necesita 8+ caracteres, mayúscula, número y símbolo).
2. Entrar al engranaje de abajo a la derecha → **Configuración Global del LLM** → completar los 3 pasos.
3. Crear un proyecto y answering la elicitación.

Si los 3 pasos funcionan, la instalación está completa.

---

## 5. Comandos útiles

### Ver estado y logs

```bash
docker compose ps                      # qué está arriba y su health
docker compose logs -f backend         # log del backend en vivo
docker compose logs -f spa             # log del frontend
docker compose logs --tail=100 backend # últimos 100 líneas
```

### Reiniciar

```bash
docker compose restart backend          # reinicia solo el backend
docker compose up -d --build backend    # reconstruye la imagen y reinicia
docker compose down                     # para todo (conserva los datos)
docker compose down -v                  # para todo Y borra los volúmenes (se pierden los datos)
```

> **`down -v` borra la base.** Se pierde la configuración de LLM y los proyectos.
> Para empezar de cero a propósito: `docker compose down -v && docker compose up -d`.

### Datos

```bash
docker compose exec -T backend python scripts/init_db.py        # aplica schema.sql
docker compose exec -T backend python -m migrations.run_migrations  # migraciones
docker compose exec -T backend python scripts/seed_patterns.py  # (re)indexa patrones
docker compose exec -T backend python scripts/seed.py           # datos de ejemplo
```

### Tests

```bash
# Backend: el schema y las migraciones primero, si no los tests de DB fallan
docker compose exec -T backend python scripts/init_db.py
docker compose exec -T backend python -m migrations.run_migrations
docker compose exec -T backend pytest tests/ -q

# Frontend: necesita Node local (el Dockerfile solo compila, no testea)
cd frontend && npm install && npm run test:run
```

### El walk end-to-end de HU10

```bash
docker compose -f docker-compose.yml -f docker-compose.walk.yml -p walk-hu10 up -d --build postgres-app backend
python scripts/walk_hu10_e2e.py
docker compose -f docker-compose.yml -f docker-compose.walk.yml -p walk-hu10 down -v
```

Levanta un stack **aislado** en los puertos 18xxx y recorre el flujo completo de fases.

---

## 6. Troubleshooting

### Docker

**`failed to connect to the docker API at npipe:////./pipe/dockerDesktopLinuxEngine`**

Docker Desktop está instalado pero **apagado**. Abrilo y esperá a que el ícono quede sin el spinner.

**`port is already allocated`**

Otro proceso ocupa el puerto. Ver cuáles:

```bash
docker compose ps -a          # contenedores viejos ocupando puertos
netstat -ano | findstr :5173  # en Windows
```

`docker compose down` y volvé a levantar. Si el puerto lo tiene otro programa (un Postgres local, por ejemplo), cambiá el mapeo en `docker-compose.yml`.

**`container name "/clickhouse" is already in use`**

Los servicios del compose tienen `container_name` fijo, así que **no podés levantar dos clones del repo al mismo tiempo**. Si tenés otro clon corriendo, bajalo:

```bash
docker compose down        # en el otro clon
```

**El stack se cae solo después de un rato**

Casi siempre es **memoria**. Docker Desktop → Settings → Resources → subí la memoria disponible.

### Base de datos

**`relation "projects" does not exist`**

Faltó aplicar el schema. El backend lo hace al arrancar, así que normalmente significa que se saltó el `init_db`:

```bash
docker compose exec -T backend python scripts/init_db.py
docker compose exec -T backend python -m migrations.run_migrations
```

**`CREATE EXTENSION "vector" is not available`**

La imagen de Postgres no trae pgvector. `docker-compose.yml` ya usa `pgvector/pgvector:pg16`; si cambiaste la imagen, volvé a la original.

### LLM

**El wizard del LLM devuelve 500 al guardar la API key**

`ENCRYPTION_KEY` no es una clave Fernet válida. Regenerala:

```bash
python -m scripts.generate_encryption_key
```

y poné el resultado en `.env`, después `docker compose restart backend`.

**`model is not supported` o 400 al generar la propuesta**

El modelo no acepta `temperature`. Hay modelos de razonamiento (serie `o*` de OpenAI, `gpt-5` sin chat, MiniMax-M3) que la rechazan. La app ya omite el parámetro para esos casos; si persiste, revisá `LLM_MODELS_WITHOUT_TEMPERATURE` en `.env`.

**El modelo devuelve bloques `<think>` en la respuesta**

Los modelos de razonamiento escriben su análisis antes de la respuesta. En el chat se ve raro y en el ADR queda **dentro del documento entregable**. No es un bug de la app: es el comportamiento del modelo.

### Engram

**`http://localhost:7439/health` no responde (la conexión se corta)**

Falta el servicio `engram-proxy`, que es el que puentea el 7439 del host al 7438 de Engram:

```bash
docker compose up -d engram-proxy
```

Es un servicio aparte del `engram`, así que si levantaste solo algunos (`docker compose up -d postgres-app backend spa`) no está. El sintoma es confuso: el puerto está publicado y Engram figura "healthy", pero la conexión se corta al instante.

**El puerto 7437 está ocupado por tu Engram local (Gentle AI)**

Por eso el compose publica el 7439 → 7437 interno. Si igual choca, cambiá el mapeo a `"7437:7437"` en `docker-compose.yml` y ajustá `ENGRAM_URL`.

**Engram siempre figura "healthy"**

Su healthcheck termina en `|| exit 0`, así que **nunca falla**, esté vivo o no. Para comprobarlo de verdad:

```bash
curl -fsS http://localhost:7439/health
```

### Frontend

**La SPA carga pero la API no responde**

Mirá el log del backend: `docker compose logs -f backend`. Suele ser el CORS o que el backend no terminó de arrancar.

**Después de tocar `frontend/`, los cambios no se ven**

El navegador cachea el bundle. `Ctrl+Shift+R`, o reconstruí: `docker compose up -d --build spa`.

### Puertos y servicios que no hacen falta

Langfuse, ClickHouse, MinIO y Redis son para **observabilidad**. Si no los vas a usar, `docker compose up -d postgres-app backend spa` alcanza y levanta en la mitad de tiempo.

---

## 7. Despliegue en producción

El deploy es por **tag semver**, disparando `deploy-railway.yml`:

```bash
# 1. main actualizado y con los checks en verde
git checkout main && git pull

# 2. El tag
git tag v0.1.0 && git push origin v0.1.0
```

El flujo completo, los secrets de Railway, la protección de ramas y el **rollback** están en [`CI-CD.md`](CI-CD.md).

**Lo que hay que configurar en Railway una sola vez:**

| Dónde | Qué |
|---|---|
| Railway → proyecto → Settings → Tokens | Crear un token **de proyecto** y ponerlo como secret `RAILWAY_TOKEN` en GitHub |
| GitHub → Settings → Secrets | `RAILWAY_TOKEN` (secret) |
| GitHub → Settings → Variables | `RAILWAY_SERVICE` = nombre del servicio backend |
| Railway → servicio backend | `RAILWAY_DOCKERFILE_PATH=backend/Dockerfile` |

> `RAILWAY_TOKEN` es un token **de proyecto**, no de cuenta. El CLI de Railway
> los distingue y con el equivocado el deploy falla con un error poco claro.

---

## Checklist del KR

Para medir el tiempo de instalación desde cero:

```bash
# 0. Docker Desktop corriendo
# 1. Clonar
git clone https://github.com/danielCH26/arch-agent.git && cd arch-agent
# 2. Setup (genera claves, levanta, espera al backend)
bash scripts/setup-local.sh
# 3. Verificar
curl -fsS http://127.0.0.1:8000/docs -o /dev/null && echo "API OK"
curl -fsS http://localhost:5173 -o /dev/null && echo "SPA OK"
```

**Objetivo: < 30 minutos.**

Medido en una máquina limpia (sin contenedores previos):

| Paso | Tiempo |
|---|---|
| Clonar + `.env` + generar las claves | ~1 min |
| **Build de la imagen del backend** (sin caché) | **~10 min** |
| Build de la imagen del SPA (sin caché) | ~1 min |
| `docker compose up -d` (arranque + schema + migraciones) | ~1 min |
| Verificar las URLs | ~1 min |
| **Total** | **~14 min** |

Casi todo es el build del backend: instala las wheels de **torch CPU** (~2 GB). Si las imágenes ya están en tu caché de Docker, el stack levanta en **menos de 1 minuto**.

Si te pasás, casi siempre es una de estas dos:

| Causa | Qué hacer |
|---|---|
| Sin `scripts/setup-local.sh` | Corrélo: automatiza claves + espera |
| Stack completo (Langfuse, ClickHouse, MinIO, Redis) | Levantá solo `postgres-app backend spa` |

---

## Ver también

- [`docs/usuario/`](usuario/README.md) — guía de uso de la app
- [`CI-CD.md`](CI-CD.md) — pipelines, secrets de Railway, protección de ramas, rollback
- [`ARCHITECTURE.md`](ARCHITECTURE.md) — cómo está armado el backend
- [`F19_ALCANCE_Y_DESPLIEGUE.md`](F19_ALCANCE_Y_DESPLIEGUE.md) — alcance del retrieval y su despliegue
