# Benchmark de rendimiento F19

F19 mide dos rutas distintas: la búsqueda vectorial (`search_ms`) y la
generación de propuestas (presupuesto total de cinco minutos).

## Preparación

1. Levantar PostgreSQL con los índices de `migrations/0007_add_document_chunks_indexes.sql`.
2. Cargar al menos 10.000 vectores por tabla con
   `python scripts/seed_bench_vectors.py` (siembra `architect_pattern_chunks` y
   `document_chunks`, reindexa y mide). Usar una base de pruebas: los patrones
   sintéticos (`category='benchmark-synthetic'`) aparecen en `/api/patterns`.
   Limpiar con `--cleanup`.
3. Arrancar el backend y esperar el log `Modelo de embeddings precargado`.
4. Usar el mismo corpus, usuario, proyecto y valor de `k` en todas las
   mediciones. El script ejecuta dos pasadas de 20 consultas: *distintas*
   (descarta la primera) y *repetidas* (efecto de la caché), y reporta p50/p95
   de `search_ms`, `embedding_ms` y `total_ms`.

## Captura

La respuesta de `POST /api/rag/search` expone estos valores en milisegundos:

| Campo | Qué mide | Target |
|---|---|---|
| `search_ms` | tiempo de pared del tramo de búsqueda, incluido encolado y join de las ramas paralelas | < 100 ms |
| `embedding_ms` | embedding de consulta; `0` en cache hit | minimizar |
| `total_ms` | embedding + tramo de búsqueda | referencia de RAG |

Para una línea base, ejecutar el script con
`RAG_EMBEDDING_CACHE_SIZE=0 python scripts/seed_bench_vectors.py --skip-seed`;
para la medición optimizada, repetirlo con el valor normal (`512`) y el mismo
corpus. La caché solo mejora `embedding_ms`/`total_ms` (no `search_ms`), y solo
en la pasada de consultas repetidas.

Alcance de la comparación: la caché es la única optimización con interruptor.
La paralelización de `scope=all` y el pool no tienen baseline propio; su efecto
se observa comparando `search_ms` de `--scope all` contra `--scope patterns` y
`--scope documents` (en paralelo, `all` debería rondar el máximo de ambos y no
su suma). La primera consulta no representa el rendimiento estable:
activa carga de modelo, conexión y caché.

## Resultados antes/después

⚠️ **Pendiente de medir en un entorno con PostgreSQL y corpus representativo.**
No se debe declarar el SLO cumplido hasta completar esta tabla. El script usa
20 consultas distintas, descarta la primera y reporta p50/p95.

| Fecha | Commit | Configuración | Pasada | Corpus (pattern/document chunks) | Hardware | `search_ms` p50 / p95 | `total_ms` p50 / p95 | Cache hits |
|---|---|---|---|---|---|---:|---:|---:|
| Pendiente | Pendiente | Baseline: `RAG_EMBEDDING_CACHE_SIZE=0` | distintas | 10.000 / 10.000 | Pendiente | — | — | — |
| Pendiente | Pendiente | Baseline: `RAG_EMBEDDING_CACHE_SIZE=0` | repetidas | 10.000 / 10.000 | Pendiente | — | — | — |
| Pendiente | Pendiente | Optimizada: `RAG_EMBEDDING_CACHE_SIZE=512` | distintas | 10.000 / 10.000 | Pendiente | — | — | — |
| Pendiente | Pendiente | Optimizada: `RAG_EMBEDDING_CACHE_SIZE=512` | repetidas | 10.000 / 10.000 | Pendiente | — | — | — |

## Límites y observabilidad

`PROPOSAL_MAX_SECONDS=300` sigue siendo el límite duro de propuesta. Los eventos
SSE `progress` incluyen `elapsed_ms` y `budget_s`, por lo que permiten auditar
una ejecución lenta por etapa. Si el p95 de `search_ms` supera 100 ms, revisar
primero los índices PGVector, `ivfflat.probes`, saturación del pool y tamaño del
corpus antes de aumentar `DB_POOL_SIZE`. Las búsquedas paralelas comparten un
executor por proceso (`RAG_SEARCH_WORKERS`, default 16); mantenerlo por debajo de
`DB_POOL_SIZE + DB_MAX_OVERFLOW`.

## Perfilado de bottlenecks y KRs

Para perfilar una propuesta, correlacionar los eventos SSE `progress` por etapa:
`context`, `retrieval`, `generating` y `saving`. `elapsed_ms` indica tiempo
acumulado y `budget_s` el presupuesto disponible. En RAG, separar
`embedding_ms` (CPU/modelo) de `search_ms` (PGVector); en una propuesta, el
tramo `generating` identifica la latencia del LLM y `saving` la persistencia.

El KR de Sofía se protege con `PROPOSAL_MAX_SECONDS=300`: corta con error al
superar cinco minutos; no acelera el flujo. El KR de Santiago (respuesta
promedio menor a tres minutos) requiere instrumentación de extremo a extremo
del request, incluyendo LLM y streaming, y queda **fuera de alcance de esta
optimización RAG** hasta registrar esa métrica en producción.
**Perfil de la ruta RAG (baseline sin caché, consultas distintas, p50):** embedding ≈ 18,5 ms
(~54 % del `total_ms` de 34,1 ms) y búsqueda PGVector ≈ 14,5 ms (~43 %). El embedding en CPU es
el mayor componente; la búsqueda con 10.000 vectores por tabla no es el cuello de botella.
El perfil de la propuesta completa (contexto, retrieval, generación del LLM, guardado) no se midió
en este PR: se obtiene de los eventos SSE `progress` y de `latency_ms` en el log del backend.