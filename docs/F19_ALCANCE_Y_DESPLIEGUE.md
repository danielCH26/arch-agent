# F19 — alcance real del PR, cambios de contrato y despliegue

Este documento existe porque el PR de F19 incluye, además de la optimización de
latencia, trabajo de otras historias (en particular `hu09-primera-propuesta-5min`)
que no cambia solo rendimiento. Lo ideal es separarlo en otro PR; mientras tanto
queda documentado aquí.

## Qué incluye el PR

| Bloque | Contenido |
|---|---|
| F19 / HU9 (latencia) | caché de embeddings, pool de conexiones, paralelización de `scope=all`, batch de documentos, warm-up del modelo, `PROPOSAL_MAX_SECONDS`, evento SSE `progress`, "Cancelar" / "Reintentar" |
| Complejidad de patrones | `migrations/0018_add_pattern_complexity.sql`, `complexity` en los 10 YAML de `data/patterns/`, `PROPOSAL_COMPLEXITY_PENALTY` y la descalificación dura de patrones de complejidad alta en proyectos pequeños |
| Contexto del proyecto | `app/core/project_context.py` y cambios en `elicitation_agent.py` |
| Endpoints nuevos | `GET /api/projects/{id}/proposals` (historial) y `GET /api/projects/{id}/proposals/latest` (vigente, excluye rechazadas) |
| CI | `.github/workflows/ci.yml`: pytest (con `pgvector/pgvector:pg16`) y vitest + build del frontend en cada PR y en cada push a `main` |
| Proxy del frontend | `frontend/nginx.conf`: `proxy_read_timeout` de 300 s a 330 s (tope de `PROPOSAL_MAX_SECONDS` + margen) |
| UI de fases | `frontend/src/api/phases.ts` (fases y etiquetas), `ChatWindow` y `PhaseBadge` (cada fase tiene su pantalla y el letrero muestra el nombre real); el PR también toca `Layout` |
| Prompts del agente | `app/core/agent.py`: ajustes del prompt de sistema (persona y *hints* de librerías y diagramas) |
| Elicitación | `app/api/elicitation.py`: la respuesta del usuario se guarda **antes** de pedirle la siguiente pregunta al LLM, así un fallo del LLM ya no la pierde |
| Limpieza | borrado de `resolve-merge-conflicts.patch` |

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
