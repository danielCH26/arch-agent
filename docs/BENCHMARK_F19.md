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
La paralelización de `scope=all`, el pool y el batching de embeddings no tienen baseline propio; su efecto
se observa comparando `search_ms` de `--scope all` contra `--scope patterns` y
`--scope documents` (en paralelo, `all` debería rondar el máximo de ambos y no
su suma). La primera consulta no representa el rendimiento estable:
activa carga de modelo, conexión y caché.

## Resultados antes/después

Corpus sintético de 10.000 vectores por tabla (`architect_pattern_chunks` y
`document_chunks`), k=5, Docker, 20 consultas por pasada (la primera de las
distintas se descarta).

- Fecha: 2026-10-03
- Hardware: AMD Ryzen 7 5700G (8 núcleos / 16 hilos), 14 GB RAM, Windows; Docker con 16 CPUs y ~7 GB de memoria
- Scope medido: all

| Configuración | Pasada | `search_ms` p50 / p95 | `total_ms` p50 / p95 | Cache hits |
| --- | --- | --- | --- | --- |
| Baseline (`RAG_EMBEDDING_CACHE_SIZE=0`) | distintas | 12,74 / 13,99 | 30,60 / 35,21 | 0 % |
| Baseline (`RAG_EMBEDDING_CACHE_SIZE=0`) | repetidas | 13,92 / 17,59 | 35,78 / 55,99 | 0 % |
| Optimizada (`RAG_EMBEDDING_CACHE_SIZE=512` - patterns) | distintas | 5,30 / 6,26 | 23,50 / 26,17 | 0 % |
| Optimizada (`RAG_EMBEDDING_CACHE_SIZE=512` - patterns) | repetidas | 3,80 / 4,47 | 3,80 / 4,47 | 100 % |
| Optimizada (`RAG_EMBEDDING_CACHE_SIZE=512` - documents) | distintas | 12,21 / 13,07 | 31,26 / 34,71 | 0 % |
| Optimizada (`RAG_EMBEDDING_CACHE_SIZE=512` - documents) | repetidas | 10,84 / 11,78 | 10,84 / 11,78 | 100 % |

- **Búsqueda RAG < 100 ms:** `search_ms` p95 entre 15 y 19 ms en todas las filas
  (el 13,61 es un p50). `total_ms` p95 sin caché: 36,88 ms (distintas) y 47,42 ms
  (repetidas).
- **Caché:** en consultas repetidas, `total_ms` p50 baja de 35,95 a 13,61 ms
  (−62 %) y p95 de 47,42 a 14,96 ms (−68 %). En consultas distintas no hay
  diferencia. `search_ms` no depende de la caché: las diferencias de ~1,5 ms entre
  filas son ruido de la medición (19 a 20 muestras por pasada; el p95 es casi el
  máximo).
- **Paralelización (`scope=all`):** p50 14,89 ms, frente a patrones solos 14,02 ms
  y documentos solos 12,25 ms. Queda en la rama más lenta (+~0,9 ms) y no en la
  suma (~26,3 ms).
- **Pool y batching de embeddings:** no tienen baseline propio; no se midió una
  mejora atribuible a ninguno de los dos.

### Limitaciones de la medición

- Vectores sintéticos aleatorios: la latencia es representativa, el recall no se
  midió.
- Un solo usuario y un solo proyecto son dueños de todos los `document_chunks`
  sintéticos. Con ivfflat el filtro por `user_id`/`project_id` se aplica sobre los
  candidatos de las listas visitadas (`ivfflat.probes`), así que con datos
  multiusuario reales la latencia y el número de resultados pueden diferir. No se
  verificó con `EXPLAIN` el uso del índice.
- Una sola conexión y consultas secuenciales: no se mide carga concurrente, el
  pool ni `RAG_SEARCH_WORKERS`.
- El beneficio real de la caché depende del hit rate en producción. Las consultas
  de retrieval de una propuesta concatenan nombre, descripción, requerimientos y
  feedback, por lo que rara vez se repiten: la caché ayuda sobre todo a
  `/api/rag/*` y al chat.

## Límites y observabilidad

`PROPOSAL_MAX_SECONDS=300` sigue siendo el límite duro de propuesta. Los eventos
SSE `progress` incluyen `elapsed_ms` y `budget_s`, por lo que permiten auditar
una ejecución lenta por etapa. Si el p95 de `search_ms` supera 100 ms, revisar
primero los índices PGVector, `ivfflat.probes`, saturación del pool y tamaño del
corpus antes de aumentar `DB_POOL_SIZE`. Las búsquedas paralelas comparten un
executor por proceso (`RAG_SEARCH_WORKERS`, default 16); mantenerlo por debajo de
`DB_POOL_SIZE + DB_MAX_OVERFLOW`.

## Perfilado de bottlenecks y KRs

### Ruta RAG

Baseline sin caché, consultas distintas, p50: embedding ≈ 18,5 ms (~54 % del
`total_ms` de 34,1 ms) y búsqueda PGVector ≈ 14,5 ms (~43 %). Los percentiles de
cada componente no suman exactamente el del total (por eso queda ~3 % sin
asignar). El embedding en CPU es el mayor componente; con 10.000 vectores por
tabla la búsqueda no es el cuello de botella.

### Propuesta completa (KR de Sofía, < 5 min)

Se midió en el frontend, con la pestaña Network del navegador (flujo
`EventStream` de `POST /api/proposals/generate`): el evento `progress` de cada
etapa trae `elapsed_ms` y el evento `done` trae el `elapsed_ms` total. Se hicieron
2 corridas con `openai/gpt-oss-20b`. Resultado reportado: **total 2,41 s**
(contexto 0,52 s, retrieval 0,48 s, generación 1,15 s, guardado 0,26 s).

Es una medición manual de dos corridas con un modelo rápido: sirve como
referencia, no como distribución. Con otro proveedor o modelo la generación
domina el tiempo (ver el tope abajo). Para repetirla, correlacionar los eventos
SSE `progress` por etapa: `context`, `retrieval`, `generating` y `saving`;
`elapsed_ms` es el tiempo acumulado y `budget_s` el presupuesto disponible. El log
del backend registra `latency_ms` por propuesta guardada.

`PROPOSAL_MAX_SECONDS=300` es el límite duro: corta con error al superar cinco
minutos, no acelera el flujo. En la práctica las etapas de trabajo (contexto,
retrieval, LLM) deben terminar antes de `300 − PROPOSAL_SAVE_RESERVE_S` (10 s por
defecto); el guardado usa ese margen. En la etapa `saving` el hilo de la base de
datos no se puede abortar a la fuerza, así que en un caso extremo la fila podría
guardarse después del corte.

### KR de Santiago (respuesta promedio < 3 min)

Requiere instrumentación de extremo a extremo del request, incluyendo LLM y
streaming, y queda **fuera de alcance de esta optimización RAG** hasta registrar
esa métrica en producción.
