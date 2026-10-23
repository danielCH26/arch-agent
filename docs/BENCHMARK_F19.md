# Benchmark de rendimiento F19

F19 mide dos rutas distintas: la búsqueda vectorial (`search_ms`) y la
generación de propuestas (presupuesto total de cinco minutos).

## Preparación

1. Levantar PostgreSQL con los índices de `migrations/0007_add_document_chunks_indexes.sql`.
2. Cargar al menos 10.000 vectores por tabla con
   `python scripts/seed_bench_vectors.py` (siembra `architect_pattern_chunks` y
   `document_chunks`, reindexa, ejecuta `ANALYZE` y mide). Usar una base de
   pruebas: los patrones sintéticos (`category='benchmark-synthetic'`) aparecen en
   `/api/patterns`. Limpiar con `--cleanup`.
   Antes de medir, el script imprime el `EXPLAIN` de cada consulta e indica si usa
   el índice ivfflat (`USA` / `NO USA`); si dice `NO USA`, la latencia medida no es
   la de PGVector con índice y hay que investigarlo antes de dar el resultado por
   válido.
3. Arrancar el backend y esperar el log `Modelo de embeddings precargado`.
4. Usar el mismo corpus, usuario, proyecto, `k` y `--scope` en todas las
   mediciones (baseline y optimizada deben compararse con el mismo scope). El
   script ejecuta dos pasadas de `--queries` consultas (default 100): *distintas*
   (descarta la primera) y *repetidas* (efecto de la caché), y reporta p50/p95
   de `search_ms`, `embedding_ms` y `total_ms`. Con `--markdown "<etiqueta>"`
   imprime las filas listas para la tabla de abajo.

## Captura

Las métricas salen de `rag.similarity_search()` (es lo que llama
`scripts/seed_bench_vectors.py`) y se registran en el log del backend
(`rag search embedding_ms=… search_ms=…`). La respuesta pública de
`POST /api/rag/search` solo expone `search_ms`: `embedding_ms`, `total_ms` y
`embedding_cached` se quitaron porque la caché se comparte entre usuarios y un
`embedding_ms` de 0 (o `total_ms − search_ms`) revelaría que otro usuario ya
consultó ese texto exacto.

| Campo | Qué mide | Target | ¿En la API pública? |
|---|---|---|---|
| `search_ms` | tiempo de pared del tramo de búsqueda, incluido encolado y join de las ramas paralelas | < 100 ms | sí |
| `embedding_ms` | embedding de consulta; `0` en cache hit | minimizar | no (log / script) |
| `total_ms` | embedding + tramo de búsqueda | referencia de RAG | no (log / script) |

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
`document_chunks`), k=5, Docker, `--queries 100` por pasada (la primera de las
distintas se descarta: 99 y 100 muestras), `--scope all` en todas las filas.

- Fecha: 2026-10-03
- Hardware: AMD Ryzen 7 5700G (8 núcleos / 16 hilos), 14 GB RAM, Windows; Docker con 16 CPUs y ~7 GB de memoria
- Scope medido: all
- `EXPLAIN`: patrones **usa** `idx_pattern_chunks_embedding` (ivfflat); documentos
  **no usa** `document_chunks_embedding_idx` (ver Limitaciones)

| Configuración | Pasada | `search_ms` p50 / p95 | `total_ms` p50 / p95 | Cache hits |
| --- | --- | --- | --- | --- |
| Baseline (`RAG_EMBEDDING_CACHE_SIZE=0`) | distintas | 13,12 / 14,45 | 32,17 / 36,82 | 0 % |
| Baseline (`RAG_EMBEDDING_CACHE_SIZE=0`) | repetidas | 13,35 / 17,18 | 32,55 / 52,11 | 0 % |
| Optimizada (`RAG_EMBEDDING_CACHE_SIZE=512`) | distintas | 13,22 / 17,13 | 33,23 / 44,92 | 0 % |
| Optimizada (`RAG_EMBEDDING_CACHE_SIZE=512`) | repetidas | 12,05 / 14,18 | 12,05 / 14,18 | 100 % |

Referencia por scope (misma corrida de 100 consultas, caché activa; `search_ms`
no depende de la caché):

| Scope | Pasada | `search_ms` p50 / p95 | `total_ms` p50 / p95 |
| --- | --- | --- | --- |
| patterns | distintas | 5,65 / 7,08 | 25,54 / 35,47 |
| documents | distintas | 12,20 / 13,27 | 31,40 / 37,22 |

- **Búsqueda RAG < 100 ms:** `search_ms` p95 entre 14 y 17 ms en todas las filas de
  `scope=all`; máximo observado 26,20 ms. `total_ms` p95 sin caché: 36,82 ms
  (distintas) y 52,11 ms (repetidas).
- **Caché (leer con cuidado):** el −63 % / −73 % de abajo sale de una sola
  situación: repetir **exactamente el mismo texto** con 100 % de cache hits, un
  escenario artificial (ver "Limitaciones": las consultas reales casi nunca se
  repiten). **Con consultas distintas la versión optimizada no mejora: en p95 es
  peor** (`search_ms` 14,45 → 17,13 ms y `total_ms` 36,82 → 44,92 ms). Con esta
  muestra no se puede separar el ruido de CPU de una regresión real, así que no
  se afirma ninguna mejora fuera del caso de repetición exacta. En consultas
  repetidas, `total_ms` p50 baja de 32,55 a 12,05 ms
  (−63 %) y p95 de 52,11 a 14,18 ms (−73 %). En consultas distintas la caché no
  interviene: la diferencia entre filas (p50 32,17 frente a 33,23 ms; p95 36,82
  frente a 44,92 ms) viene del tiempo del embedding en CPU, que varía entre
  corridas (p95 de `embedding_ms` 23,24 frente a 27,41 ms), no de la caché. Con 99
  muestras el p95 es casi el cuarto valor más alto, así que es sensible a una
  corrida.
- **Paralelización (`scope=all`):** `search_ms` p50 13,22 ms (distintas), frente a
  patrones solos 5,65 ms y documentos solos 12,20 ms. Queda cerca de la rama más
  lenta (+~1,0 ms) y no de la suma (17,85 ms): ahorra ~4,6 ms (~26 %). El ahorro es
  acotado porque las dos ramas son asimétricas; con ramas de duración parecida
  sería mayor.
- **Pool y batching de embeddings:** no tienen baseline propio; no se midió una
  mejora atribuible a ninguno de los dos.

### Limitaciones de la medición

- Vectores sintéticos aleatorios: la latencia es representativa, el recall no se
  midió.
- **Documentos: el planner no usó el índice ivfflat.** El `EXPLAIN` de la consulta
  real muestra `Index Scan using idx_document_chunks_document_id` seguido de un
  `Sort` por distancia: filtra por documento con el índice b-tree y ordena de forma
  exacta. La latencia de ~12 ms de `document_chunks` corresponde a ese plan, no a
  una búsqueda aproximada con ivfflat (y, al ser exacta, no pierde resultados por
  `ivfflat.probes`). Con un corpus real (muchos documentos y usuarios) el plan
  puede cambiar y no se verificó. El plan de patrones sí usa
  `idx_pattern_chunks_embedding`.
- Un solo usuario y un solo proyecto son dueños de todos los `document_chunks`
  sintéticos, así que el filtro por `user_id`/`project_id` no discrimina; con datos
  multiusuario la latencia y el número de resultados pueden diferir.
- Una sola conexión y consultas secuenciales: **no se validó con carga
  concurrente**. Ni el pool, ni `RAG_SEARCH_WORKERS`, ni la paralelización de
  `scope=all` bajo varios usuarios simultáneos están medidos; los valores por
  defecto (10 + 20 conexiones, 16 hilos) son una estimación, no un resultado.
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
executor por proceso (`RAG_SEARCH_WORKERS`, default 16). El dimensionamiento
completo del pool (por proceso y contra `max_connections` de PostgreSQL, incluido
el executor de `asyncio.to_thread`) está en `.env.example`.

## Perfilado de bottlenecks y KRs

### Ruta RAG

Baseline sin caché, consultas distintas, p50: embedding ≈ 19,06 ms (~59 % del
`total_ms` de 32,17 ms) y búsqueda ≈ 13,12 ms (~41 %). Los percentiles de cada
componente no tienen por qué sumar exactamente el del total (aquí suman 32,18 ms).
El embedding en CPU es el mayor componente; con 10.000 vectores por tabla la
búsqueda no es el cuello de botella.

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
datos no se puede abortar a la fuerza. Para que "Cancelar" o el corte por tiempo no
dejen una iteración guardada (que gastaría una de `PROPOSAL_MAX_ITER`), el
generador marca un `threading.Event` que el hilo de guardado comprueba **justo
antes del `commit`** y, si está marcado, hace rollback. Es best-effort: si el
`commit` ya empezó cuando llega la cancelación no hay forma de deshacerlo, y la
propuesta queda guardada; por eso el front resincroniza con
`GET /api/projects/{id}/proposals/latest` al cancelar.

### KR de Santiago (respuesta promedio < 3 min)

Requiere instrumentación de extremo a extremo del request, incluyendo LLM y
streaming, y queda **fuera de alcance de esta optimización RAG** hasta registrar
esa métrica en producción.
