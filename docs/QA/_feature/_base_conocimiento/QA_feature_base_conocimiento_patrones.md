# QA - Base de conocimiento inicial de patrones arquitectónicos

Feature: Crear la base de conocimiento inicial con patrones arquitectónicos  
Responsable: Laura  
Labels: feature, sprint-2, backend

## Objetivo

Validar que el backend carga una base inicial de patrones arquitectónicos con metadata completa, trade-offs en JSONB y embeddings vectoriales, y que la búsqueda semántica retorna patrones relevantes.

## Preparación

Desde la raíz del proyecto:

```powershell
docker compose build backend
docker compose up -d postgres-app backend
docker compose exec backend python migrations/run_migrations.py
docker compose exec backend python scripts/seed_patterns.py
```

Resultado esperado del seed:

```text
Patrones procesados: 10. Chunks (re)generados: 40
```

Si aparece `No se encontraron archivos .yaml en /app/data/patterns`, reconstruir backend otra vez con:

```powershell
docker compose build --no-cache backend
docker compose up -d backend
```

## Criterio 1 - Al menos 10 patrones cargados

Ejecutar:

```powershell
docker compose exec postgres-app psql -U asistente -d asistente_db -c "SELECT COUNT(*) AS total_patrones FROM architect_patterns;"
```

Resultado esperado:

```text
 total_patrones
----------------
             10
```

Verificar nombres:

```powershell
docker compose exec postgres-app psql -U asistente -d asistente_db -c "SELECT pattern_name, category FROM architect_patterns ORDER BY pattern_name;"
```

Debe incluir, por nombre exacto o equivalente directo:

- Monolito: `Arquitectura en capas (Layered)` y/o `Monolito modular (Modular Monolith)`
- Microservicios: `Microservicios`
- Event-driven: `Arquitectura orientada a eventos (Event-Driven)`
- CQRS: `CQRS (Command Query Responsibility Segregation)`
- Hexagonal / Ports & Adapters: `Arquitectura hexagonal (Puertos y Adaptadores)`
- Clean Architecture: `Clean Architecture`
- Serverless: `Serverless (Function-as-a-Service)`
- BFF: `API Gateway + Backend for Frontend (BFF)`

## Criterio 2 - Cada patrón tiene descripción completa

Ejecutar:

```powershell
docker compose exec postgres-app psql -U asistente -d asistente_db -c "SELECT pattern_name FROM architect_patterns WHERE description IS NULL OR length(trim(description)) < 80 OR use_cases IS NULL OR length(trim(use_cases)) < 40;"
```

Resultado esperado:

```text
(0 rows)
```

Validar estructura obligatoria:

```powershell
docker compose exec postgres-app psql -U asistente -d asistente_db -c "SELECT pattern_name FROM architect_patterns WHERE pattern_name IS NULL OR category IS NULL OR description IS NULL OR use_cases IS NULL OR tradeoffs IS NULL OR embedding IS NULL;"
```

Resultado esperado:

```text
(0 rows)
```

Validar trade-offs JSONB con ventajas y desventajas:

```powershell
docker compose exec postgres-app psql -U asistente -d asistente_db -c "SELECT pattern_name FROM architect_patterns WHERE jsonb_typeof(tradeoffs) <> 'object' OR jsonb_typeof(tradeoffs->'ventajas') <> 'array' OR jsonb_array_length(tradeoffs->'ventajas') < 2 OR jsonb_typeof(tradeoffs->'desventajas') <> 'array' OR jsonb_array_length(tradeoffs->'desventajas') < 2;"
```

Resultado esperado:

```text
(0 rows)
```

Validar embeddings principales:

```powershell
docker compose exec postgres-app psql -U asistente -d asistente_db -c "SELECT COUNT(*) AS patrones_sin_embedding FROM architect_patterns WHERE embedding IS NULL;"
```

Resultado esperado:

```text
 patrones_sin_embedding
------------------------
                      0
```

## Criterio extra - Chunks de búsqueda generados

La feature original pide embeddings por patrón. La implementación actual además genera chunks por campo para mejorar el retrieval.

Ejecutar:

```powershell
docker compose exec postgres-app psql -U asistente -d asistente_db -c "SELECT chunk_type, COUNT(*) FROM architect_pattern_chunks GROUP BY chunk_type ORDER BY chunk_type;"
```

Resultado esperado:

```text
 chunk_type        | count
-------------------+-------
 decision_signals  |    10
 summary           |    10
 tradeoffs         |    10
 when_not_to_use   |    10
```

Validar que ningún chunk quedó sin embedding:

```powershell
docker compose exec postgres-app psql -U asistente -d asistente_db -c "SELECT COUNT(*) AS chunks_sin_embedding FROM architect_pattern_chunks WHERE embedding IS NULL;"
```

Resultado esperado:

```text
 chunks_sin_embedding
----------------------
                    0
```

## Criterio 3 - Búsqueda retorna patrones relevantes

Primero obtener un token válido con un usuario real de la app. Guardarlo en PowerShell:

```powershell
$TOKEN = "PEGAR_TOKEN_AQUI"
```

### Caso A - Microservicios

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri "http://localhost:8000/api/rag/search" `
  -Headers @{ Authorization = "Bearer $TOKEN" } `
  -ContentType "application/json" `
  -Body '{"query":"tengo varios equipos que necesitan desplegar servicios por separado y escalar modulos independientemente","scope":"patterns","k":5}' |
  ConvertTo-Json -Depth 8
```

Resultado esperado: entre los resultados debe aparecer `Microservicios`.

### Caso B - Hexagonal / Ports & Adapters

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri "http://localhost:8000/api/rag/search" `
  -Headers @{ Authorization = "Bearer $TOKEN" } `
  -ContentType "application/json" `
  -Body '{"query":"quiero cambiar la base de datos sin tocar reglas de negocio y probar el dominio sin servicios externos","scope":"patterns","k":5}' |
  ConvertTo-Json -Depth 8
```

Resultado esperado: entre los resultados debe aparecer `Arquitectura hexagonal (Puertos y Adaptadores)` o `Clean Architecture`.

### Caso C - Event-driven

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri "http://localhost:8000/api/rag/search" `
  -Headers @{ Authorization = "Bearer $TOKEN" } `
  -ContentType "application/json" `
  -Body '{"query":"necesito publicar eventos para que varios modulos reaccionen sin bloquearse entre si","scope":"patterns","k":5}' |
  ConvertTo-Json -Depth 8
```

Resultado esperado: entre los resultados debe aparecer `Arquitectura orientada a eventos (Event-Driven)`.

### Caso D - CQRS

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri "http://localhost:8000/api/rag/search" `
  -Headers @{ Authorization = "Bearer $TOKEN" } `
  -ContentType "application/json" `
  -Body '{"query":"mis lecturas necesitan escalar por separado y quiero vistas denormalizadas para reportes","scope":"patterns","k":5}' |
  ConvertTo-Json -Depth 8
```

Resultado esperado: entre los resultados debe aparecer `CQRS (Command Query Responsibility Segregation)`.

## Endpoint de catálogo

Validar que el endpoint de solo lectura devuelve los patrones actuales:

```powershell
Invoke-RestMethod `
  -Uri "http://localhost:8000/api/patterns" `
  -Headers @{ Authorization = "Bearer $TOKEN" } |
  ConvertTo-Json -Depth 8
```

Resultado esperado:

- Devuelve una lista de 10 patrones.
- Cada patrón incluye `id`, `pattern_name`, `category`, `description`, `use_cases`, `tradeoffs` y `when_not_to_use`.
- `tradeoffs` llega como objeto JSON, no como texto plano.

## Prueba desde el front

Entrar al frontend y hacer estas preguntas en el chat:

```text
Tengo un equipo pequeño y un CRUD simple, ¿qué arquitectura me conviene?
```

Esperado: recomienda una alternativa monolítica simple, como arquitectura en capas, y muestra fuentes relacionadas con patrones.

```text
Necesito que varios módulos reaccionen a cambios sin bloquear el flujo principal.
```

Esperado: recomienda o menciona arquitectura orientada a eventos y muestra fuentes relacionadas.

```text
Quiero separar lecturas de escrituras porque mis reportes son mucho más pesados.
```

Esperado: recomienda o menciona CQRS y muestra fuentes relacionadas.

## Resultado de aceptación

La feature se acepta si:

- Hay 10 o más patrones en `architect_patterns`.
- Todos tienen nombre, categoría, descripción, casos de uso, trade-offs JSONB y embedding.
- Los chunks de `architect_pattern_chunks` existen y tienen embeddings.
- `/api/patterns` devuelve el catálogo actual.
- `/api/rag/search` devuelve patrones coherentes para consultas sobre microservicios, event-driven, CQRS, hexagonal, clean architecture, serverless, BFF y alternativas monolíticas.
