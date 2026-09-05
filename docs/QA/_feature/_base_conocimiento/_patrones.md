# QA - Base de conocimiento de patrones

## Alcance

Validar la ingesta interna de fuentes PDF/MD para enriquecer la busqueda semantica de patrones de arquitectura.

Esta feature no expone endpoints nuevos al cliente final. La ingesta se ejecuta por CLI y solo crea registros en `architect_pattern_chunks` asociados a un `pattern_id` existente.

## Preparacion

1. Levantar servicios:

```bash
docker compose up -d
```

2. Aplicar migraciones:

```bash
docker compose exec backend python migrations/run_migrations.py
```

3. Confirmar que existe un patron destino:

```bash
docker compose exec postgres-app psql -U asistente -d asistente_db -P pager=off -c "SELECT id, pattern_name, category FROM architect_patterns ORDER BY id;"
```

4. Elegir el `id` del patron correcto. Ejemplo: si el PDF es de microservicios, usar el `id` que aparezca junto a `Microservicios`.

5. Tener a mano un archivo `.pdf` o `.md` menor o igual a 10 MB en `fuentes/`. Esa carpeta se monta dentro del contenedor backend como `/app/fuentes`.

## Caso feliz

Ejecutar:

```bash
docker compose exec backend python scripts/ingest_pattern_source.py --pattern-id 20009 --file fuentes/on-micro-services-architecture.pdf
```

Resultado esperado:

- El comando imprime `Ingesta completada: N chunks insertados en pattern_id=20009`.
- `N` es mayor a 0.
- Los chunks quedan con `chunk_type = 'source_upload'`.
- Los chunks quedan con `embedding` no nulo.
- `chunk_metadata` contiene `filename` y `source_type`.

Verificacion SQL:

```bash
docker compose exec postgres-app psql -U asistente -d asistente_db -P pager=off -c "SELECT pattern_id, chunk_type, chunk_metadata, embedding IS NOT NULL AS has_embedding FROM architect_pattern_chunks WHERE pattern_id = 20009 AND chunk_type = 'source_upload' ORDER BY id DESC LIMIT 5;"
```

## Validaciones negativas

Archivo con extension no soportada:

```bash
docker compose exec backend python scripts/ingest_pattern_source.py --pattern-id 20009 --file fuentes/notas.txt
```

Resultado esperado:

- Falla sin insertar chunks.
- Muestra `Formato no soportado. Solo: .md, .pdf`.

Archivo mayor a 10 MB:

```bash
docker compose exec backend python scripts/ingest_pattern_source.py --pattern-id 20009 --file fuentes/grande.pdf
```

Resultado esperado:

- Falla sin insertar chunks.
- Muestra `El archivo excede el límite de 10 MB`.

`pattern_id` inexistente:

```bash
docker compose exec backend python scripts/ingest_pattern_source.py --pattern-id 999999 --file fuentes/event-driven.pdf
```

Resultado esperado:

- Falla sin crear chunks huerfanos.
- Muestra `pattern_id 999999 no existe`.

## No regresion

Confirmar que los campos curados no cambian por correr la ingesta:

```bash
docker compose exec postgres-app psql -U asistente -d asistente_db -P pager=off -c "SELECT id, description, tradeoffs, decision_signals FROM architect_patterns WHERE id = 20009;"
```

Resultado esperado:

- `description`, `tradeoffs`, `decision_signals`, `use_cases` y `when_not_to_use` permanecen iguales antes y despues de ejecutar el script.
- `app/api/patterns.py` sigue siendo solo lectura y no se modifico para esta feature.
- `app/core/rag.py` no se modifico; la busqueda semantica ya toma cualquier chunk con embedding no nulo.

## Criterios de aceptacion

- [ ] Un PDF/MD valido para un `pattern_id` existente crea N chunks en `architect_pattern_chunks`.
- [ ] Los chunks creados tienen `embedding` no nulo.
- [ ] Los chunks creados tienen `chunk_metadata.filename` y `chunk_metadata.source_type`.
- [ ] Una query semanticamente relevante puede devolver estos chunks mediante `similarity_search_patterns_by_vector`.
- [ ] Extension no soportada falla con el mensaje esperado.
- [ ] Archivo mayor a 10 MB falla con el mensaje esperado.
- [ ] `pattern_id` inexistente falla con mensaje claro y no crea chunks.
- [ ] La ingesta no modifica campos curados de `architect_patterns`.
- [ ] No se agregaron endpoints publicos ni cambios en `app/api/patterns.py`.
