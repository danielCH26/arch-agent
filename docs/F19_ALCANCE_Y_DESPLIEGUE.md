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
| Limpieza | borrado de `resolve-merge-conflicts.patch` |

## Cambios de contrato de la API (no son "sin modificar contratos")

- `POST /api/proposals/generate` puede responder **409** *antes* de abrir el stream
  SSE (se alcanzó `PROPOSAL_MAX_ITER`). Es una respuesta JSON normal con `detail`,
  no un evento `error` del stream. Un cliente que solo esperaba `text/event-stream`
  debe tratar el 409.
- `POST /api/proposals/{id}/modify` añade dos 409 nuevos: la propuesta ya no es la
  última iteración, o ya existe una posterior (además de los 409 previos de estado
  y de máximo de iteraciones).
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
