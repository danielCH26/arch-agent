# QA — Pipeline RAG (Embeddings + PGVector + LangChain)

**Feature:** Pipeline de Retrieval-Augmented Generation
**Responsable:** Laura
**Labels:** feature, sprint-2, backend

Este documento es la guía para que QA / el reviewer valide los criterios de aceptación de la HU, paso a paso, sin necesidad de leer el código.

---

## Pre-requisitos antes de probar

```powershell
docker compose build backend
docker compose up -d backend
docker compose exec backend python -m migrations.run_migrations
```

Sembrar los patrones de arquitectura (necesario para tener datos con embeddings):

```powershell
docker compose exec backend python scripts/seed_patterns.py
```

Confirmar que quedaron con embedding generado:

```powershell
docker compose exec postgres-app psql -U asistente -d asistente_db -c "SELECT count(*) AS total, count(embedding) AS con_embedding FROM architect_patterns;"
```
✅ Esperado: `con_embedding` = `total` (ningún patrón con embedding en `NULL`).

Necesitas un usuario logueado (token JWT) para las pruebas de API — inicia sesión desde la UI o vía `POST /api/auth/login` y guarda el token.

> **Sobre configurar el LLM:** `POST /api/rag/search` (usado en el Criterio 1 vía `curl`) **no** requiere tener un LLM configurado — solo el JWT del usuario, ya que solo hace retrieval, no genera texto. Si en cambio prefieres probar la búsqueda de patrones **desde el chat de la UI** (ver sección "Extra" más abajo), ahí sí necesitas tener un LLM configurado para tu usuario — sin eso, `POST /api/chat` devuelve `409 LLM not configured for user` antes de siquiera llegar al retrieval. Configúralo en la sección de ajustes de LLM de la app (`/api/llm/*`) antes de probar por esa vía.

> **Si el chat responde pero no muestra patrones guardados:** primero valida el retrieval crudo con `POST /api/rag/search` y `scope: "patterns"`. Si ese endpoint devuelve patrones, la base/seed están bien y probablemente el chat los está filtrando por `RAG_MIN_SIMILARITY = 0.85`. Si ese endpoint devuelve `results: []`, revisa que la migración `0005_add_architect_patterns.sql` se haya aplicado y vuelve a correr `scripts/seed_patterns.py`.

---

## Criterio 1 — Búsqueda de patrones retorna resultados relevantes

**Componente probado:** `POST /api/rag/search` → `app/core/rag.py::similarity_search`

### Pasos
1. Con el token JWT, llama:
   ```powershell
   curl -X POST http://localhost:8000/api/rag/search `
     -H "Content-Type: application/json" `
     -H "Authorization: Bearer TU_TOKEN" `
     -d '{"query":"que arquitectura me conviene si mi sistema debe crecer por modulos independientes","scope":"patterns"}'
   ```
2. Repite con una query claramente distinta, ej. `"como puedo optimizar por separado las lecturas y las escrituras de una aplicacion"`.
3. Repite con una query sin relación al dominio, ej. `"receta de pan de banano"`.

### Resultado esperado
- [ ] La query de microservicios devuelve como primer resultado (`results[0]`) el patrón **"Arquitectura de microservicios"** (o equivalente), con `metadata.similarity` alto (> 0.7 aprox.).
- [ ] La query de CQRS devuelve el patrón de **CQRS** primero, no microservicios.
- [ ] Los resultados vienen **ordenados de mayor a menor similitud** (revisa que `similarity` vaya descendiendo en la lista).
- [ ] La query sin relación al dominio (ej. "receta de pan de banano") devuelve resultados — `/api/rag/search` siempre trae los top-k más cercanos, no hay corte por relevancia en ese endpoint. **No esperes que `similarity` caiga drásticamente**: con `multilingual-e5-small` una query totalmente ajena al dominio igual devolvió patrones al 75-78% de similitud en pruebas reales (ver hallazgo abajo). Lo que sí debe cumplirse es que sea **más baja** que la similitud de una query relevante (que suele rondar 85-95%+), aunque no caiga a valores bajos en términos absolutos.
- [ ] Cada resultado trae `content` (texto del patrón) y `metadata.source_type = "architect_pattern"`.

### ⚠️ Hallazgo real durante esta ronda de pruebas (ya corregido)

Al probar con "receta de pan de banano" **desde el chat de la UI** (no `/api/rag/search` directo), pasaron dos cosas:

1. El LLM respondió con una receta completa de pan de banano usando su conocimiento general — correcto, ya que no hay contenido real de recetas en la base vectorial.
2. Pero el chat igual mostró el bloque **"Fuentes (PGVector)"** citando 5 patrones de arquitectura (Backend for Frontend, Arquitectura hexagonal, CQRS, Event sourcing, Arquitectura de microservicios) con 75-78% de similitud — **dando la impresión falsa de que la receta salió de esas fuentes**, cuando no tienen ninguna relación real.

**Causa:** `similarity_search()` en `app/core/rag.py` no aplica ningún umbral mínimo de similitud — siempre devuelve los top-k más cercanos que encuentre, sin importar qué tan irrelevantes sean en términos absolutos.

**Fix aplicado:** se agregó `RAG_MIN_SIMILARITY = 0.85` en `app/api/chat.py`. Los documentos recuperados con `similarity` por debajo de ese umbral se descartan antes de usarse en el prompt del LLM y antes de mostrarse en el evento `sources` / bloque "Fuentes (PGVector)" de la UI. `/api/rag/search` (el endpoint crudo, usado en las pruebas con `curl` de este documento) **no** tiene este filtro — sigue devolviendo el top-k sin cortar, a propósito, para que QA/debug pueda ver la similitud real sin filtrar. El filtro vive solo en la capa del chat, que es donde el problema de "atribución engañosa" ocurre.

**Para re-probar este caso puntual:**
1. Preguntar en el chat de la UI algo totalmente ajeno al dominio (ej. "receta de pan de banano", "capital de Francia").
2. ✅ Esperado ahora: el chat responde con conocimiento general y muestra el aviso **"Sin contexto recuperado de la base vectorial..."**, no un bloque de fuentes con patrones irrelevantes.
3. Si aun así aparecen fuentes con similitud claramente irrelevante, bajar `RAG_MIN_SIMILARITY` no es la solución (ya está filtrando) — revisar si esa query en particular sí superó el 85% por casualidad semántica y ajustar el umbral con más casos de prueba antes de cambiarlo.

**✅ Verificado tras el fix:** se repitió la pregunta de la receta de pan de banano en el chat de la UI. Resultado: la respuesta se generó con conocimiento general del modelo (receta completa y correcta) y, debajo, apareció **"Sin contexto recuperado de la base vectorial — respuesta basada en conocimiento general del modelo"** — sin ningún patrón de arquitectura citado. El umbral `RAG_MIN_SIMILARITY = 0.85` descartó correctamente los 5 documentos irrelevantes que antes se mostraban al 75-78%.

---

## Criterio 2 — Chunks de documentos subidos son consultables

**Componente probado:** subida de documento → procesamiento a chunks → `POST /api/rag/search` con `scope: "documents"`

### Pasos
1. Sube un documento (PDF/MD/TXT) desde la UI a un proyecto, o vía `POST /api/documents/upload`.
2. Espera a que se marque como procesado (`processed: true`):
   ```powershell
   docker compose exec postgres-app psql -U asistente -d asistente_db -c "SELECT id, filename, processed FROM uploaded_documents ORDER BY id DESC LIMIT 5;"
   ```
3. Confirma que se generaron chunks con embedding:
   ```powershell
   docker compose exec postgres-app psql -U asistente -d asistente_db -c "SELECT document_id, count(*) AS chunks, count(embedding) AS con_embedding FROM document_chunks GROUP BY document_id ORDER BY document_id DESC LIMIT 5;"
   ```
4. Busca por contenido que sepas que está en ese documento:
   ```powershell
   curl -X POST http://localhost:8000/api/rag/search `
     -H "Content-Type: application/json" `
     -H "Authorization: Bearer TU_TOKEN" `
     -d '{"query":"frase o concepto literal que aparezca en el documento subido","scope":"documents","project_id":ID_DEL_PROYECTO}'
   ```

### Resultado esperado
- [x] El documento queda `processed = true` después de subirlo (sin quedarse colgado en `false`).
- [x] Existen filas en `document_chunks` para ese `document_id`, todas con `embedding` no nulo.
- [x] La búsqueda por `scope: "documents"` devuelve chunks de **ese** documento con contenido relevante a la query.
- [ ] Sube un segundo documento con **otro usuario** (o revisa el código) y confirma que un usuario **no puede** recuperar chunks de documentos de otro usuario (ownership — ver `similarity_search_document_chunks_by_vector`, filtra por `user_id`).
- [ ] Si pasas `project_id`, solo trae chunks de ese proyecto (no de todos los proyectos del usuario).

**✅ Evidencia real:** se subió un PDF sobre representaciones de grafos/MapReduce y se preguntó en el chat de la UI sobre representaciones gráficas de grafos. La respuesta citó correctamente **`MapReduce-algorithms-91-107.pdf`** dos veces (81% y 80% de similitud) en el bloque "Fuentes (PGVector)" — confirma que el pipeline sí recupera y usa contenido real del documento subido, no solo lo simula.

### ⚠️ Hallazgo adicional: el umbral de 0.80 no es suficiente cuando `scope="all"` mezcla patrones y documentos

En la misma prueba de arriba, junto a los 2 chunks reales del PDF, se colaron **3 patrones de arquitectura irrelevantes** (Arquitectura hexagonal 82%, Event sourcing 82%, CQRS 81%) — sin relación con grafos/MapReduce, pero con similitud por encima del umbral de 0.80.

**Causa:** el chat usa `scope="all"`, así que `similarity_search()` siempre junta top-k de **ambos** grupos (patrones de arquitectura + chunks de documentos) y los mezcla por distancia — cuando la query solo tiene relación real con uno de los dos grupos, el otro igual aporta "ruido" que puede superar el umbral por casualidad semántica (los patrones de arquitectura son textos técnicos, y comparten vocabulario general con casi cualquier tema de ingeniería/sistemas).

**Pendiente de decidir (no corregido aún):**
- Subir `RAG_MIN_SIMILARITY` por encima de 0.82-0.83 (con más casos de prueba antes de fijar el número final), o
- Aplicar el umbral **por grupo** en vez de global (ej. solo mostrar patrones si superan X, y chunks de documentos si superan Y, en vez de un único corte para ambos), o
- Cuando hay chunks de documentos con buena similitud (>0.85), descartar directamente los patrones de arquitectura del resultado — si el usuario subió un documento y pregunta sobre su contenido, es poco probable que también quiera "patrones de arquitectura" genéricos mezclados.

Este es un ajuste fino de calidad, no un bug bloqueante — el umbral ya evita el caso extremo (receta de pan de banano con 0 relación), pero falta afinarlo para casos "medio relacionados".

### 🔒 Decisión final: `RAG_MIN_SIMILARITY = 0.85` (umbral único, no diferenciado por tipo)

Se probaron dos enfoques (umbral por tipo, dominancia relativa entre grupos) y ambos fallaron contra evidencia real adicional recolectada. El caso definitivo: preguntar por microservicios (con un PDF de matemáticas ya subido) devolvió el patrón correcto de "Arquitectura de microservicios" (88%) **y**, incorrectamente, chunks del PDF de matemáticas (83% — más alto que un documento verdadero de otro caso, a 80-81%). Esto probó matemáticamente que **ningún umbral (global o por tipo) puede acertar en todos los casos**, porque un falso positivo de un caso puede tener mayor similitud que un verdadero positivo de otro.

**Evidencia acumulada usada para fijar el número:**
| | Similitud |
|---|---|
| Verdadero positivo — patrón (microservicios) | 88% |
| Verdadero positivo — documento (módulo cuantitativo) | 89-92% |
| Falso positivo — patrón (pan de banano) | 75-78% |
| Falso positivo — patrón (grafos/MapReduce) | 81-82% |
| Falso positivo — documento (microservicios → PDF matemáticas) | 83% |

`0.85` cae en el hueco entre el falso positivo más alto (83%) y el verdadero positivo más bajo (88%) — acierta en **3 de 4 casos probados**. El caso que sacrifica: la pregunta de grafos/MapReduce pierde también sus chunks de documento verdaderos (80-81%), porque ese score cae por debajo de 0.85 junto con los patrones falsos del mismo caso.

**Esto es una limitación conocida y documentada, no un bug pendiente:** con `multilingual-e5-small`, la similitud coseno sola no separa perfectamente relevante/irrelevante en la banda 80-88%. Si en el futuro se necesita precisión real ahí, la solución correcta es agregar un paso de **re-ranking** (el LLM juzgando relevancia real de cada candidato, o un cross-encoder) — eso queda fuera del alcance de esta HU (ver `app/api/chat.py`, comentario junto a `RAG_MIN_SIMILARITY`).

---

## Criterio 3 — Tiempo de búsqueda < 100ms para 10k vectores ✅ CUMPLIDO

**Componente probado:** `search_ms` en la respuesta de `similarity_search` (excluye el tiempo de generar el embedding de la query, solo mide la consulta a PGVector).

**Evidencia (`scripts/seed_bench_vectors.py`, corrido dentro del contenedor `backend` — `docker compose exec backend python scripts/seed_bench_vectors.py` —, 10,000 vectores sintéticos 384d + `REINDEX` del índice `ivfflat`):**

```
search_ms -> avg=5.73ms  min=4.31ms  max=12.25ms  p95=6.32ms
✅ CRITERIO 3 CUMPLIDO: todas las busquedas < 100ms
```

- avg **5.73ms**, p95 **6.32ms** — ~17x más rápido que el límite de 100ms.
- El único pico (12.25ms, primera query) es cold-cache normal justo después del `REINDEX`; las siguientes 9 corridas se estabilizan en 4-6ms.
- Consistente con una corrida previa local contra el mismo Postgres (avg 7.34ms) — confirma que el número no depende del entorno de ejecución, solo de PGVector/el índice.

### Pasos para reproducir
1. Poblar con vectores sintéticos y correr el benchmark (necesita rebuild si el script no estaba ya en la imagen):
   ```powershell
   docker compose build backend
   docker compose up -d backend
   docker compose exec backend python scripts/seed_bench_vectors.py
   ```
2. Limpiar los datos sintéticos al terminar:
   ```powershell
   docker compose exec backend python scripts/seed_bench_vectors.py --cleanup
   ```

### Resultado esperado
- [x] Con ~10k vectores, `search_ms` se mantiene consistentemente **por debajo de 100ms**.
- [x] El índice `ivfflat` está creado sobre la columna `embedding` (`idx_architect_patterns_embedding` en `schema.sql`) y sostiene el volumen sin degradar a full scan.
- [x] `SET LOCAL ivfflat.probes = 10` no generó timeouts ni resultados vacíos a este volumen.

---

## Checklist de componentes (del ticket original)

- [ ] **Embeddings con multilingual-e5-small (384d):** confirmar en `app/core/embeddings.py` que `EMBEDDING_MODEL_NAME = "intfloat/multilingual-e5-small"` y `EMBEDDING_DIM = 384`, y que `schema.sql` define las columnas `embedding` como `vector(384)`.
- [ ] **Vector store con PGVector:** confirmar extensión `vector` habilitada en Postgres (`docker compose exec postgres-app psql -U asistente -d asistente_db -c "\dx"` → debe listar `vector`).
- [ ] **Búsqueda semántica (similarity_search):** cubierto por Criterios 1 y 2 arriba.
- [ ] **Integración con LangChain:** confirmar que `similarity_search` devuelve objetos `langchain_core.documents.Document` (ver respuesta de `/api/rag/search`, o revisar `app/core/rag.py`).
- [ ] **Tablas `architect_patterns`, `document_chunks`:** confirmar que existen con `\dt` en psql y que tienen los índices `ivfflat` (ver Criterio 3).

---

## Extra — Trazabilidad en el chat (no pedido explícitamente en el ticket, pero recomendado)

El chat (`POST /api/chat`, usado desde la UI) ahora expone qué fuentes de PGVector usó para cada respuesta vía el evento SSE `event: sources`, visible en la UI como un bloque "Fuentes (PGVector)" debajo de cada mensaje del asistente (o el aviso de "sin contexto recuperado" si no hubo match).

- [ ] Preguntar algo que matchee con un patrón sembrado, por ejemplo: `"quiero cambiar la base de datos sin tocar las reglas de negocio, que arquitectura recomiendas"` → debe aparecer el bloque de fuentes con nombre + % de similitud.
- [ ] Repetir con otro patrón sembrado, por ejemplo: `"mi aplicacion va a crecer por partes y necesito desplegar cada modulo por separado, que opcion ves mejor"` → debe aparecer **Microservicios** entre las fuentes.
- [ ] Preguntar algo fuera de dominio → debe aparecer el aviso de que no se encontró contexto relevante.

Esto sirve como evidencia visual rápida de los Criterios 1 y 2 sin tener que llamar la API a mano.

---

## Bugs encontrados y ya corregidos durante esta ronda de pruebas (contexto para el reviewer)

1. **Markdown crudo en el chat** — el LLM a veces envolvía toda la respuesta en un solo bloque ` ``` `, mostrando tablas/negritas sin renderizar. Corregido con instrucción explícita en el prompt + fallback en `MessageBubble.tsx`.
2. **Sin trazabilidad de fuentes RAG** — no había forma de confirmar desde la UI si una respuesta usó PGVector o el conocimiento general del modelo. Corregido con el evento `sources` (ver sección "Extra" arriba).
3. **Build del frontend roto** — faltaba `frontend/.dockerignore`, causando que `node_modules` local pisara el del contenedor. Corregido.
4. **Atribución engañosa de fuentes RAG** — el chat mostraba "Fuentes (PGVector)" citando patrones de arquitectura irrelevantes (75-78% similitud) para preguntas totalmente ajenas al dominio (ej. una receta de cocina), porque `similarity_search()` no tenía umbral mínimo de relevancia. Corregido con `RAG_MIN_SIMILARITY = 0.85` en `app/api/chat.py` — ver detalle en Criterio 1.

## Fallos preexistentes, no relacionados con esta HU (no bloquean el merge, pendientes aparte)

- `tests/api/test_auth.py::test_login_request` y `tests/api/test_documents.py` (3 tests) — modelos Pydantic (`LoginRequest`, `DocumentOut`) y firmas de endpoints desincronizados con sus tests.
- `tests/test_document_storage.py` (20 tests) — requieren Postgres real accesible en `localhost:5432`; fallan por credenciales en entornos donde no está configurado.
