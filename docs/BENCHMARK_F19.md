# Benchmark de rendimiento F19

F19 mide dos rutas distintas: la búsqueda vectorial (`search_ms`) y la
generación de propuestas (presupuesto total de cinco minutos).

## Preparación

1. Levantar PostgreSQL con los índices de `migrations/0007_add_document_chunks_indexes.sql`.
2. Cargar al menos 10.000 vectores representativos (por ejemplo,
   `python scripts/seed_bench_vectors.py`).
3. Arrancar el backend y esperar el log `Modelo de embeddings precargado`.
4. Usar el mismo usuario, proyecto, consulta y valor de `k` en todas las
   mediciones. Ejecutar 20 consultas, descartar la primera y reportar p50/p95.

## Captura

La respuesta de `POST /api/rag/search` expone estos valores en milisegundos:

| Campo | Qué mide | Target |
|---|---|---|
| `search_ms` | tiempo de pared del tramo de búsqueda, incluido encolado y join de las ramas paralelas | < 100 ms |
| `embedding_ms` | embedding de consulta; `0` en cache hit | minimizar |
| `total_ms` | embedding + tramo de búsqueda | referencia de RAG |

Para una línea base, iniciar temporalmente con
`RAG_EMBEDDING_CACHE_SIZE=0`; para la medición optimizada, usar el valor
normal (`512`). La primera consulta no representa el rendimiento estable:
activa carga de modelo, conexión y caché.

## Resultados antes/después

⚠️ **Pendiente de medir en un entorno con PostgreSQL y corpus representativo.**
No se debe declarar el SLO cumplido hasta completar esta tabla. El script usa
20 consultas distintas, descarta la primera y reporta p50/p95.

| Fecha | Commit | Configuración | Corpus (pattern/document chunks) | Hardware | p50 `search_ms` | p95 `search_ms` | Cache hits |
|---|---|---|---|---|---:|---:|---:|
| Pendiente | Pendiente | Baseline: `RAG_EMBEDDING_CACHE_SIZE=0` | 10.000 / 10.000 | Pendiente | — | — | — |
| Pendiente | Pendiente | Optimizada: `RAG_EMBEDDING_CACHE_SIZE=512` | 10.000 / 10.000 | Pendiente | — | — | — |

## Límites y observabilidad

`PROPOSAL_MAX_SECONDS=300` sigue siendo el límite duro de propuesta. Los eventos
SSE `progress` incluyen `elapsed_ms` y `budget_s`, por lo que permiten auditar
una ejecución lenta por etapa. Si el p95 de `search_ms` supera 100 ms, revisar
primero los índices PGVector, `ivfflat.probes`, saturación del pool y tamaño del
corpus antes de aumentar `DB_POOL_SIZE`.

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
