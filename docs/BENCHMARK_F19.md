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
| `search_ms` | tramo PGVector; con `scope=all` es el máximo de las ramas paralelas | < 100 ms |
| `embedding_ms` | embedding de consulta; `0` en cache hit | minimizar |
| `total_ms` | embedding + tramo de búsqueda | referencia de RAG |

Para una línea base, iniciar temporalmente con
`RAG_EMBEDDING_CACHE_SIZE=0`; para la medición optimizada, usar el valor
normal (`512`). La primera consulta no representa el rendimiento estable:
activa carga de modelo, conexión y caché.

Registra los resultados en el PR/incidente con fecha, commit, tamaño de corpus,
hardware, p50, p95 y el porcentaje de cache hits. Así un cambio de modelo o de
índice no se atribuye equivocadamente a esta optimización.

## Límites y observabilidad

`PROPOSAL_MAX_SECONDS=300` sigue siendo el límite duro de propuesta. Los eventos
SSE `progress` incluyen `elapsed_ms` y `budget_s`, por lo que permiten auditar
una ejecución lenta por etapa. Si el p95 de `search_ms` supera 100 ms, revisar
primero los índices PGVector, `ivfflat.probes`, saturación del pool y tamaño del
corpus antes de aumentar `DB_POOL_SIZE`.
