# Guía de despliegue

Cómo levantar Arch-Agent en local y desplegarlo en producción.

**Tiempo objetivo: menos de 30 minutos** para tener el stack andando desde cero.
Al final está el [checklist](#8-checklist-del-kr) para medirlo.

- Instalación local → esta página
- Uso de la app (registro, primer proyecto) → [`docs/usuario/01-inicio-rapido.md`](usuario/01-inicio-rapido.md)
- Problemas frecuentes de la app → [`docs/usuario/03-faq.md`](usuario/03-faq.md)
- Pipelines de CI y despliegue a Railway → [`CI-CD.md`](CI-CD.md)

---

## 1. Requisitos

| Qué | Versión | Para qué |
|---|---|---|
| **Docker Desktop** | Compose v2 | Corre todo el stack. En Windows tiene que estar **corriendo** (icono en la bandeja), no solo instalado. La v2.24+ hace falta solo para el `docker-compose.walk.yml` (usa `!override`) |
| **Git** | cualquiera | Clonar el repo |
| RAM | 8 GB libres | El stack levanta 13 servicios; con menos, Postgres compite con Docker y falla |
| Disco | 6 GB libres | Imágenes de Docker + modelos de embeddings (~470 MB) |
| Puertos libres | 3000, 5173, 5432, 7439, 8000 | Los usa el stack (ver [tabla](#servicios-y-puertos)) |

**Para correr la app no hace falta Python ni Node locales**: todo corre dentro de Docker. Sí hacen falta para dos cosas opcionales: correr los tests ([§5](#5-comandos-útiles)) y el walk end-to-end.

> **Windows:** `docker compose` (con espacio, sin guion) es Compose v2. Si tenés `docker-compose` con guion, es v1 y **no sirve** para `docker-compose.walk.yml`.

---

## 2. Instalación local

### Opción A — el script (recomendada)

```bash
git clone https://github.com/danielCH26/arch-agent.git
cd arch-agent
bash scripts/setup-local.sh
```

El script es **re-ejecutable**: detecta qué pasos ya hizo y se los salta. Genera `JWT_SECRET_KEY` y `ENCRYPTION_KEY` **si están vacías** (y las escribe en el `.env`), levanta el stack y espera a que el backend responda.

Levanta también `langfuse-worker`, que no es dependencia de nadie y sin él Langfuse queda esperando su primer trace sin dar error.

### Opción B — manual

```bash
git clone https://github.com/danielCH26/arch-agent.git
cd arch-agent
cp .env.example .env

# Genera la clave Fernet. El script imprime un banner: copiá la LÍNEA
# que empieza con "ENCRYPTION_KEY=".
docker compose run --rm --no-deps backend python scripts/generate_encryption_key.py
# JWT_SECRET_KEY: cualquier string aleatorio. Ejemplo:
#   openssl rand -base64 48

docker compose up -d

# Indexa los patrones del catálogo (el backend NO lo hace al arrancar)
docker compose exec -T backend python scripts/seed_patterns.py
```

Dos pasos que no son opcionales:

- **`seed_patterns.py`**: el backend aplica `schema.sql` y las migraciones al arrancar, pero **no** indexa los patrones. Sin ese paso la tabla `architect_pattern_chunks` queda vacía y las propuestas se generan con 0 patrones citados. El único aviso es un warning en el log del backend.
- **`ENCRYPTION_KEY`**: sin ella el backend **arranca igual**, pero el wizard del LLM devuelve 500 al intentar cifrar la API key.

**Para levantar de nuevo después de tocar migraciones:**

```bash
docker compose up -d --build backend
docker compose exec -T backend python scripts/seed_patterns.py   # reindexa los patrones
```

> La clave se genera **dentro del contenedor** para no depender de Python local: el script importa `cryptography`, que no viene en un Python pelado.

---

## 3. Variables de entorno

`.env.example` tiene un montón de variables, pero **la mayoría ya vienen con un valor por defecto que funciona**. Solo hay que mirar estas:

### Necesarias para usar la app (el backend arranca sin ellas)

| Variable | Qué es | Cómo obtenerla |
|---|---|---|
| `JWT_SECRET_KEY` | Firma los tokens de sesión | Cualquier string aleatorio. El script de setup lo genera; a mano, `openssl rand -base64 48` |
| `ENCRYPTION_KEY` | Cifra la API key del LLM del usuario | **Fernet**: 32 bytes en base64 url-safe. `docker compose run --rm --no-deps backend python scripts/generate_encryption_key.py` |

> Las dos son necesarias **para usar la app**, pero el backend **arranca sin ellas** y se ve sano. Eso es lo confuso: sin `JWT_SECRET_KEY` falla al iniciar sesión (no al arrancar), y sin `ENCRYPTION_KEY` el wizard del LLM devuelve **500** al cifrar la API key.
>
> `ENCRYPTION_KEY` además tiene que ser una clave Fernet **válida** (44 caracteres base64 url-safe), no un string cualquiera.

### Para usar un LLM

| Variable | Cuándo |
|---|---|
| *(ninguna)* | Si configurás el LLM **desde la UI** (engranaje del pie de la barra lateral → Configuración del LLM). Es lo recomendado |
| `GROQ_API_KEY` | Si querés el default de backend (Groq, `openai/gpt-oss-120b`) sin tocar la UI |

> **Cuidado con `GROQ_API_KEY` si la app tiene registro abierto.** La key es del
> operador: cada cuenta nueva que se registra consume tokens de tu cuota, sin
> rate limiting por usuario. Si el registro es público, dejala vacía y que cada
> usuario configure su propia key desde la UI.

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
2. Entrar al **engranaje del pie de la barra lateral** → **Configuración del LLM** → completar los 3 pasos.
3. Crear un proyecto y responder la elicitación.

Si los 3 pasos funcionan, la instalación está completa.

> El paso 2 es el que falla si `ENCRYPTION_KEY` quedó vacía: el backend
> registra el usuario y después explota al firmar el token. Si te pasa eso,
> el problema son las claves, no la instalación.

---

## 5. Comandos útiles

### Ver estado y logs

```bash
docker compose ps                      # qué está arriba y su health
docker compose logs -f backend         # log del backend en vivo
docker compose logs -f spa             # log del frontend
docker compose logs --tail=100 backend # últimas 100 líneas
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
# Backend: en el HOST, igual que CI. Los tests NO van en la imagen del
# backend: .dockerignore excluye tests/ y el Dockerfile no los copia.
# Necesitás Python 3.11 local.
python -m pip install -r requirements.txt
python -m pip install pytest pytest-mock pytest-asyncio pytest-cov

# Para que sea "igual que CI": las wheels de torch SOLO CPU. Sin esto, pip
# baja la versión con CUDA, que son varios GB.
python -m pip install torch --index-url https://download.pytorch.org/whl/cpu

# el schema y las migraciones, contra el Postgres del stack
docker compose exec -T backend python scripts/init_db.py
docker compose exec -T backend python -m migrations.run_migrations

DATABASE_URL=postgresql://asistente:asistente@localhost:5432/asistente_db \
  python -m pytest tests/ -q

# Frontend: necesita Node local (el Dockerfile solo compila, no testea)
cd frontend && npm install && npm run test:run
```

> Si preferís no instalar nada en el host, copiá los tests al contenedor:
> `docker compose cp ./tests backend:/app/tests` y corré
> `docker compose exec -T backend pytest /app/tests -q`.
>
> Dos detalles de esa vía: si cambiaste código, **reconstruí la imagen**
> (`docker compose up -d --build backend`), porque si no los tests van contra
> un `/app/app` viejo; y el test `test_llm_yaml_tsx_parity.py` da error
> porque lee `frontend/`, que no está en la imagen del backend. Ese test
> necesita el repo completo, o sea que corre en el host.

### El walk end-to-end de HU10

```bash
docker compose -f docker-compose.yml -f docker-compose.walk.yml -p walk-hu10 up -d --build postgres-app backend
python scripts/walk_hu10_e2e.py
docker compose -f docker-compose.yml -f docker-compose.walk.yml -p walk-hu10 down -v
```

Levanta un stack **aislado** en los puertos 18xxx y recorre el flujo completo de fases.

> **Necesita `WALK_LLM_API_KEY`**: el walk llama al modelo para generar la
> propuesta, y sin la key aborta con *"WALK_LLM_API_KEY no está seteada"*.
> El script nunca la imprime. También acepta `WALK_LLM_BASE_URL` y
> `WALK_LLM_MODEL` para apuntar a otro proveedor.

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
docker compose run --rm --no-deps backend python scripts/generate_encryption_key.py
```

y poné el resultado en `.env`, después `docker compose up -d backend`.

> `restart` **no** relee el `env_file`: reinicia el contenedor con las variables
> que ya tenía. Para que una clave nueva entre hay que recrearlo con
> `docker compose up -d backend`.

**La propuesta se genera sin citar ningún patrón**

El índice de patrones está vacío. El backend aplica el schema y las migraciones al arrancar, pero **no** indexa el catálogo: eso lo hace `seed_patterns.py`.

```bash
docker compose exec -T backend python scripts/seed_patterns.py
```

El único aviso es un warning en el log del backend; en la app no se ve.

**`model is not supported` o 400 al generar la propuesta**

El modelo no acepta `temperature`. Hay modelos de razonamiento (serie `o*` de OpenAI, `gpt-5` sin chat, MiniMax-M3) que la rechazan. La app ya omite el parámetro para esos casos; si persiste, revisá `LLM_MODELS_WITHOUT_TEMPERATURE` en `.env`.

**El modelo devuelve bloques `<think>` en la respuesta**

Los modelos de razonamiento escriben su análisis antes de la respuesta. En el chat se ve raro y en el ADR queda **dentro del documento entregable**. No es un bug de la app: es el comportamiento del modelo.

### Engram

El camino real es: **host 7439 → 7437 (socat) → 7438 (Engram)**.

- Desde el **host**: `http://localhost:7439`.
- Desde el **backend** (dentro de la red de compose): `http://engram:7437`. El compose lo fija en `ENGRAM_URL`, y **el `ENGRAM_URL` de tu `.env` solo lo usan los scripts que corren en el host** (como el walk).

**`http://localhost:7439/health` no responde (la conexión se corta)**

Falta el servicio `engram-proxy`, que es el que hace de puente:

```bash
docker compose up -d engram-proxy
```

Es un servicio aparte del `engram`, así que no lo levanta cualquier `docker compose up`. El síntoma es confuso: el puerto está publicado y Engram figura "healthy", pero la conexión se corta al instante.

> Ojo: un `docker compose up -d` **completo** sí lo levanta. Lo que no lo levanta
> es pedir solo un subconjunto (`postgres-app backend spa`), porque `engram-proxy`
> no es dependencia de nadie.

**El backend también pasa por el proxy**

El compose le pone `ENGRAM_URL=http://engram:7437`, y ese 7437 **no es Engram**: lo sirve el `socat` del `engram-proxy`. Si el proxy no está, el backend tampoco alcanza a Engram, no solo el host.

**El puerto 7437 está ocupado por tu Engram local (Gentle AI)**

Por eso el compose publica el 7439 → 7437 interno. Si igual choca, cambiá el mapeo a `"7437:7437"` en `docker-compose.yml` y ajustá `ENGRAM_URL` **solo si lo usan scripts del host**.

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

### Los servicios de observabilidad

Langfuse, ClickHouse, MinIO y Redis son para **observabilidad**, pero **no se pueden dejar afuera**: el servicio `backend` declara `depends_on` de `engram`, `langfuse-web` y `puppeteer-mcp`, así que compose levanta esas dependencias y las de ellas aunque pidas solo `backend`.

```bash
docker compose up -d postgres-app backend spa   # levanta 11 contenedores, no 3
```

De los 13 servicios del compose quedan afuera **solo** `langfuse-worker` y `engram-proxy` (este último es justo el que hace falta para que Engram responda en el host, ver [Engram](#engram)).

> `langfuse-worker` no es dependencia de nadie (solo lo es de `langfuse-web`, que
> ya está), así que compose no lo levanta solo. Sin él, Langfuse queda en
> *"Waiting for first trace"* sin dar ningún error. `setup-local.sh` lo levanta
> explícitamente por eso.

Si lo que querés es un stack mínimo de verdad, hay que poner las dependencias en `profiles` o `required: false` en el `docker-compose.yml`. Eso es un cambio del compose, no un flag de la CLI.

---

## 7. Despliegue en producción

El deploy es por **tag semver**, disparando `deploy-railway.yml`. El flujo completo, los secrets, la protección de ramas y el **rollback** están en [`CI-CD.md`](CI-CD.md); esto es el resumen.

### Antes del primer deploy

1. **Desconectar el auto-deploy de GitHub** en el servicio de Railway. Si queda conectado, cada push a `main` despliega y se rompe la regla de "merge a main no despliega".
2. **Crear el environment `production` en GitHub y configurarle required reviewers.** El job de `deploy-railway.yml` ya declara `environment: production`, así que no hay que apuntarlo: si el environment no existe, **GitHub lo crea solo y sin protección**, y el deploy sale sin que nadie lo apruebe. Si lo creás vos, podés exigir la aprobación.
3. **Validar el workflow antes de confiarle un tag.** `workflow_dispatch` (input `ref`) apuntando a un commit de `main`, que es lo que recomienda `CI-CD.md`. Ojo: **no es un dry-run, despliega de verdad** — apuntalo a un commit de `main` y no a una rama de pruebas.
4. **Configurar el Release Command de Railway** para aplicar el schema y las migraciones (ver [abajo](#lo-que-el-workflow-no-despliega)).

### Configurar en Railway (una sola vez)

| Dónde | Qué |
|---|---|
| Railway → proyecto → Settings → Tokens | Crear un token **de proyecto** y ponerlo como secret `RAILWAY_TOKEN` en GitHub |
| GitHub → Settings → Secrets | `RAILWAY_TOKEN` (secret) |
| GitHub → Settings → Variables | `RAILWAY_SERVICE` = nombre del servicio backend |
| Railway → servicio backend | `RAILWAY_DOCKERFILE_PATH=backend/Dockerfile` |

> `RAILWAY_TOKEN` es un token **de proyecto**, no de cuenta. El CLI de Railway
> los distingue y con el equivocado el deploy falla con un error poco claro.

### Lo que el workflow **no** despliega

`deploy-railway.yml` sube **solo el backend**. Quedan por tu cuenta:

- **La base de datos.** El servicio de Railway necesita su Postgres con **pgvector** (`pgvector/pgvector:pg16`), y hay que configurar `DATABASE_URL` apuntando a ella.
- **El schema y las migraciones.** El `command` del compose (`init_db.py && run_migrations && uvicorn`) **solo existe en `docker-compose.yml`**. El `CMD` del `backend/Dockerfile` corre `uvicorn` pelado y `server.py` no aplica nada. Contra una base nueva, el primer deploy queda sin tablas, y cada migración posterior queda sin aplicar.
  Configurá el **Release Command** del servicio de Railway con:
  ```
  python scripts/init_db.py && python -m migrations.run_migrations
  ```
  Corre en cada deploy, antes de reemplazar la instancia.
- **El catálogo de patrones.** Después del primer deploy hay que indexarlo una vez:
  ```
  python scripts/seed_patterns.py
  ```
  Sin esto, las propuestas se generan con 0 patrones citados.
- **La SPA, Engram, Puppeteer y Langfuse.** El workflow no los despliega: son servicios aparte. Si los querés, configurá un servicio por uno con su propio `Dockerfile`.
- **Las variables de runtime** del servicio: `JWT_SECRET_KEY`, `ENCRYPTION_KEY` (Fernet válida), `POSTGRES_*`, `LANGFUSE_*`, `ENGRAM_*` y las del LLM.

> **No son las mismas de `.env.example`:** ahí `ENGRAM_URL` apunta a `localhost:7439` (el host) y `PUPPETEER_MCP_URL` a un host interno de compose. En Railway tienen que apuntar a los servicios reales.

### El deploy

```bash
# 1. main actualizado y con los checks en verde
git checkout main && git pull

# 2. El tag
git tag v0.1.0 && git push origin v0.1.0
```

---

## 8. Checklist del KR

Para medir el tiempo de instalación desde cero:

```bash
# 0. Docker Desktop corriendo
# 1. Clonar
git clone https://github.com/danielCH26/arch-agent.git && cd arch-agent
# 2. Setup (genera claves, levanta, espera al backend)
bash scripts/setup-local.sh
# 3. Verificar
curl -fsS http://127.0.0.1:8000/docs  -o /dev/null && echo "API OK"
curl -fsS http://localhost:5173       -o /dev/null && echo "SPA OK"
curl -fsS http://localhost:7439/health -o /dev/null && echo "Engram OK"
```

**Objetivo: < 30 minutos.**

Lo que mide esta tabla, con las imágenes ya descargadas:

| Paso | Tiempo |
|---|---|
| Clonar + `.env` + generar las claves | ~1 min |
| **Build de la imagen del backend** (sin caché) | **~10 min** |
| Build de la imagen del SPA (sin caché) | ~1 min |
| `docker compose up -d` (arranque + schema + migraciones) | ~1 min |
| Verificar las URLs | ~1 min |
| **Total de builds y arranque** | **~14 min** |

Casi todo es el build del backend: instala las wheels de **torch CPU** (~2 GB). Si las imágenes ya están en tu caché de Docker, el stack levanta en **menos de 1 minuto**.

> **Lo que esta tabla NO mide**, y por lo tanto el objetivo de 30 minutos **todavía no está demostrado en una máquina limpia**:
>
> - La **descarga de las imágenes de terceros**: Langfuse (web, worker, db), ClickHouse, ClickHouse keeper, MinIO, Redis, Engram, socat, pgvector. Con la caché de Docker fría son varios GB y dependen de la conexión.
> - El **build de `puppeteer-mcp`**, que instala Chromium.
> - La **descarga del modelo de embeddings** (~470 MB) que hace `seed_patterns.py` al indexar el catálogo.
>
> Medido de punta a punta con la caché vacía, el número es mayor que 30 minutos. **Para que el KR sea un hecho y no una promesa, hay que medirlo en una máquina virtual limpia y anotar el número real acá.**

Si te pasás, casi siempre es una de estas dos:

| Causa | Qué hacer |
|---|---|
| Sin `scripts/setup-local.sh` | Corrélo: automatiza claves + espera |
| Imágenes de terceros sin descargar | `docker compose pull` antes de arrancar, o dejalo correr la primera vez |

> No hay forma de levantar "solo el backend" sin las dependencias de
> observabilidad: el `backend` las declara en `depends_on` y compose las
> levanta igual. Ver [Los servicios de observabilidad](#los-servicios-de-observabilidad).

---

## Ver también

- [`docs/usuario/`](usuario/README.md) — guía de uso de la app
- [`CI-CD.md`](CI-CD.md) — pipelines, secrets de Railway, protección de ramas, rollback
- [`ARCHITECTURE.md`](ARCHITECTURE.md) — cómo está armado el backend
- [`F19_ALCANCE_Y_DESPLIEGUE.md`](F19_ALCANCE_Y_DESPLIEGUE.md) — alcance del retrieval y su despliegue
