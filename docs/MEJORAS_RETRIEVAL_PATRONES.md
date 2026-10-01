# Mejoras al retrieval de patrones

Problema: con 10 patrones y una consulta ruidosa, el LLM recibía candidatos poco
discriminados (las similitudes de `multilingual-e5-small` caen en ~0.80–0.90) y
la elección dependía de heurísticas a mano.

## Qué cambió

| Cambio | Dónde |
| --- | --- |
| 19 patrones (+MVC/MVVM, Pipes & Filters, Microkernel, SOA, Saga, ETL/ELT, Lambda/Kappa, Lakehouse Medallion, MLOps) | `data/patterns/*.yaml` |
| Campos nuevos por patrón: `quality_attributes`, `team_fit`, `example_scenarios` → chunks `scenarios` y `fit` | `data/patterns/*.yaml`, `app/core/pattern_catalog.py` |
| Perfil estructurado del proyecto → consulta redactada como un escenario | `app/core/query_profile.py` |
| El LLM reordena los candidatos del RAG; no puede saltarse las reglas duras (escala, rechazo/pedido del usuario, señal "no usar") | `app/core/pattern_ranker.py`, `_select_citations(llm_ranking=...)` |
| Búsqueda de patrones exacta sobre ivfflat (`probes` ≥ `lists`) | `app/core/rag.py` |
| Alias con `/` ("MVC / MVVM" → "mvc", "mvvm") | `_pattern_aliases` |
| Set de evaluación + script sin base de datos | `data/eval/pattern_retrieval_cases.yaml`, `scripts/eval_pattern_retrieval.py` |

Todo es best-effort: si el LLM falla, hace timeout o no responde JSON, se usa la
consulta clásica y el orden por similitud. Se apaga con
`PROPOSAL_QUERY_PROFILE=off` y `PROPOSAL_LLM_RERANK=off`.

## Después de aplicar el patch

```bash
docker compose exec backend python scripts/seed_patterns.py   # re-embebe 19 patrones × 6 chunks
python scripts/eval_pattern_retrieval.py -v                   # mide top-1 / top-3
```

No hay migración de esquema: `chunk_type` es `VARCHAR(50)` sin CHECK.

## Medir antes de cambiar de modelo de embeddings

```bash
python scripts/eval_pattern_retrieval.py --model intfloat/multilingual-e5-small
python scripts/eval_pattern_retrieval.py --model intfloat/multilingual-e5-base
python scripts/eval_pattern_retrieval.py --model BAAI/bge-m3 --query-prefix "" --passage-prefix ""
```

Solo si el candidato mejora claramente top-1/top-3, migra: cambia `vector(384)` en
`architect_pattern_chunks` **y** `document_chunks` (misma dimensión en `rag.py` y
`embeddings.py`), re-siembra los patrones y re-procesa los documentos subidos.

## Limitaciones del set de evaluación

Los 24 casos se redactaron junto con los `example_scenarios`, así que comparten
vocabulario y la métrica sale inflada. Sirve para comparar versiones; para una
nota realista agrega 5–10 casos con el estilo del proyecto del profe.
