# Pruebas para cambios de patrones RAG

Este checklist valida la migración nueva, el seed desde YAML, el endpoint de catálogo y el retrieval por chunks.

## 1. Validaciones rápidas sin base de datos

```powershell
.\venv\Scripts\python.exe -m py_compile scripts\seed_patterns.py app\core\rag.py app\api\patterns.py app\models\architect_pattern.py app\models\architect_pattern_chunk.py server.py
```

Esperado: no imprime errores.

```powershell
.\venv\Scripts\python.exe -c "import yaml, pathlib; files=sorted(pathlib.Path('data/patterns').glob('*.yaml')); data=[yaml.safe_load(f.read_text(encoding='utf-8')) for f in files]; print(len(files)); print([d['pattern_name'] for d in data])"
```

Esperado: imprime `10` y la lista de patrones cargados desde `data/patterns`.

```powershell
.\venv\Scripts\python.exe -c "import server; print('server ok')"
```

Esperado: imprime `server ok`.

```powershell
.\venv\Scripts\python.exe -m pytest tests\api\test_rag.py
```

Esperado: `5 passed`.

## 2. Migraciones

Con la base de datos levantada:

```powershell
docker compose build backend
docker compose up -d postgres-app
docker compose up -d backend
docker compose exec backend python migrations/run_migrations.py
```

Esperado: se reconstruye el backend con `data/patterns` dentro de `/app`, se aplica `0008_add_pattern_context_and_chunks.sql` o indica que no hay migraciones pendientes si ya estaba aplicada.

Verificar columnas y tabla:

```sql
SELECT column_name
FROM information_schema.columns
WHERE table_name = 'architect_patterns'
  AND column_name IN ('when_not_to_use', 'decision_signals');

SELECT to_regclass('public.architect_pattern_chunks');
```

Esperado: aparecen las dos columnas y `public.architect_pattern_chunks`.

## 3. Seed de patrones y chunks

```powershell
docker compose exec backend python scripts/seed_patterns.py
```

Esperado: log similar a:

```text
Patrones procesados: 10. Chunks (re)generados: 40
```

El total esperado es `10 patrones x 4 chunks`.

Verificar conteos:

```sql
SELECT COUNT(*) FROM architect_patterns;

SELECT chunk_type, COUNT(*)
FROM architect_pattern_chunks
GROUP BY chunk_type
ORDER BY chunk_type;
```

Esperado: `architect_patterns` mantiene 10 filas y cada `chunk_type` (`summary`, `tradeoffs`, `when_not_to_use`, `decision_signals`) tiene 10 filas.

## 4. Endpoint de catálogo

Con un Bearer token válido:

```powershell
Invoke-RestMethod `
  -Uri "http://localhost:8000/api/patterns" `
  -Headers @{ Authorization = "Bearer TU_TOKEN" }
```

Esperado: lista de patrones ordenada por `pattern_name`, incluyendo `when_not_to_use`.

## 5. Retrieval por chunks

Con un Bearer token válido:

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri "http://localhost:8000/api/rag/search" `
  -Headers @{ Authorization = "Bearer TU_TOKEN" } `
  -ContentType "application/json" `
  -Body '{"query":"mi equipo es de 4 personas y tiene presupuesto operativo bajo","scope":"patterns","k":5}'
```

Esperado: los resultados siguen teniendo `source_type = architect_pattern`, y ahora pueden incluir metadata `chunk_type` con valores como `when_not_to_use` o `decision_signals`.

## 6. Pruebas con base de datos

Estas pruebas requieren PostgreSQL local en `localhost:5432` con la base `test` disponible:

```powershell
.\venv\Scripts\python.exe -m pytest tests\test_seed_idempotent.py tests\test_document_storage.py
```

Esperado: pasan cuando la DB de test está levantada. Si PostgreSQL no está corriendo, fallan en setup con `connection refused`.
