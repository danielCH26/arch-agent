# F19 — alcance real del PR, cambios de contrato y despliegue

Este documento resume qué cambia el PR de F19, qué contratos de la API modifica
y qué hay que hacer al desplegarlo.

## Qué incluye el PR

El PR está rebaseado sobre `development`: solo contiene trabajo de F19. HU9
(`hu09-primera-propuesta-5min`) entró por su cuenta en el #95.

| Bloque | Contenido |
|---|---|
| Caché y búsqueda RAG | `app/core/rag.py`: caché LRU de embeddings de consultas (`RAG_EMBEDDING_CACHE_SIZE`), paralelización de `scope=all` y métricas al log (no en la respuesta) |
| Pool de PostgreSQL | `app/core/database.py`: pool persistente (`DB_POOL_*`) con su dimensionamiento documentado en `.env.example` |
| Variables de entorno | `app/core/env.py` (`env_int` / `env_float`): un valor vacío, no numérico o bajo el mínimo vuelve al default con un warning |
| Indexado de documentos | `app/api/documents.py`: `embed_documents` en lotes de `EMBEDDING_BATCH_SIZE` (límite de memoria, no mejora la latencia) |
| API de RAG | `app/api/rag.py`: `similarity_search` vía `asyncio.to_thread` y límite de 2000 caracteres por consulta (422) |
| Cancelar al guardar | `app/core/proposal_generator.py`: `cancel_event` comprobado antes del `commit` (rollback si se canceló); en el frontend, `cancel()` resincroniza con `/proposals/latest` al instante y a los 2 s |
| Propuestas (API) | `app/api/proposals.py`: los 409 documentados en OpenAPI y `SSE_HEARTBEAT_SECONDS` con mínimo de 1 s |
| Arranque | `server.py`: `load_dotenv()` antes de importar `app.*` (el pool lee `DB_POOL_*` al importarse) y aviso si alguien registra un `on_event` que `lifespan` ignoraría |
| Benchmark | `scripts/seed_bench_vectors.py` y `docs/BENCHMARK_F19.md` |

Ya estaban en `development` antes de este PR, y por eso **no** forman parte de
él: el tope `PROPOSAL_MAX_SECONDS`, el evento SSE `progress`, "Cancelar" /
"Reintentar" (HU9, #95), la migración `0018` y la complejidad de patrones, los
endpoints `GET /api/projects/{id}/proposals` y `/proposals/latest`, el CI
(`.github/workflows/ci.yml`), `frontend/nginx.conf` (330 s), la UI de fases, los
prompts de `app/core/agent.py` y la persistencia de respuestas en
`app/api/elicitation.py`.

## Cambios de contrato de la API (no son "sin modificar contratos")

- `POST /api/proposals/generate` puede responder **409** *antes* de abrir el stream
  SSE (se alcanzó `PROPOSAL_MAX_ITER`). Es una respuesta JSON normal con `detail`,
  no un evento `error` del stream. Un cliente que solo esperaba `text/event-stream`
  debe tratar el 409.
- `POST /api/proposals/{id}/modify` añade **un** 409 nuevo: la propuesta ya no es la
  última iteración del proyecto (es decir, existe una posterior; es una sola
  comprobación, `latest.id != prior.id`). Se suma a los 409 previos de estado y de
  máximo de iteraciones. El mensaje "La siguiente iteración no es válida" **no** es
  un 409: llega como evento SSE `error` desde el guardado, ya con el stream abierto.
- Nuevo evento SSE `progress` (aditivo: un cliente viejo lo ignora) y campo
  `elapsed_ms` en el evento `done`.
- `POST /api/rag/search`, `GET /api/rag/patterns/search` y
  `GET /api/rag/documents/search`: la respuesta **ya no incluye** `embedding_ms` ni
  `total_ms` (solo `results` y `search_ms`). Motivo: la caché de embeddings es
  compartida y esos campos revelan si otro usuario consultó el mismo texto. No hay
  consumidores en el frontend; los benchmarks usan `rag.similarity_search()`.
- `POST /api/rag/search` (`query`) y los dos `GET` (`q`) ahora rechazan con 422
  consultas de más de 2000 caracteres (`MAX_QUERY_CHARS` en `app/core/rag.py`):
  `multilingual-e5-small` trunca a 512 tokens (~2000 caracteres), así que el texto
  sobrante no cambiaba el resultado. La caché de embeddings además no guarda
  consultas más largas que ese límite aunque lleguen desde el chat o desde la
  generación de propuestas.

Los 409 aparecen documentados en OpenAPI (`/docs`) con el prefijo "antes de abrir el
stream".

## Pruebas y CI

- `pytest` y `vitest` + build corren en CI (`.github/workflows/ci.yml`); los
  números de tests de la descripción del PR deben salir de ese run, no de una
  corrida local.
- `tests/test_seed_idempotent.py` (2 tests) **se excluye del CI** con
  `--ignore=tests/test_seed_idempotent.py`: necesita el esquema completo
  (`schema.sql` + migraciones) y descargar el modelo de embeddings para sembrar.
  Hoy nada lo ejecuta automáticamente; se puede activar cuando el CI cargue las
  migraciones. Corre a mano con `python -m pytest tests/test_seed_idempotent.py`.
  El antiguo `scripts/test_seed_idempotent.py` ya no existe.
- Los tests de integración de cancelación durante el guardado
  (`tests/core/test_proposal_cancel_integration.py`) usan el Postgres real del CI.
  Documentan el límite best-effort: si el `commit` ya empezó cuando llega la
  cancelación, la propuesta queda guardada.

## Pasos obligatorios de despliegue

1. **Migración `0018`** (`ALTER TABLE architect_patterns ADD COLUMN complexity`).
   Viene de `development`, no de este PR; solo aplica si el entorno todavía no la
   tiene.
   El backend aplica las migraciones pendientes al arrancar; si usas Docker,
   reconstruye: `docker compose up -d --build backend`. Es aditiva y nullable.
2. **Sembrar los patrones** *después* de la migración:
   `python scripts/seed_patterns.py`. Sin este paso `complexity` queda en `NULL`
   y la penalización/descalificación por complejidad no tiene efecto (los
   patrones sin valor no se penalizan). El script reconcilia la tabla contra
   `data/patterns/*.yaml` y borra las filas que no estén en los YAML; **no lo
   corras sobre una base donde tengas datos de `scripts/seed_bench_vectors.py`**
   si quieres conservarlos.
3. Revisar `.env.example`: variables nuevas `PROPOSAL_*`, `RAG_*`,
   `EMBEDDING_BATCH_SIZE`, `SSE_HEARTBEAT_SECONDS`, `DB_POOL_*`.
4. Dimensionar conexiones con la fórmula de `.env.example` (por proceso y contra
   `max_connections` de PostgreSQL) **antes** de subir el número de workers de
   uvicorn: con los defaults, cada proceso puede abrir hasta 30 conexiones.
