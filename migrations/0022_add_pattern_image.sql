-- =============================================================================
-- Migration 0022: architect_patterns.image / image_alt / image_source
-- =============================================================================
-- Imagen ilustrativa de cada patron para la seccion "Base de patrones".
--   image        ruta local servida por el frontend (/pattern-images/<archivo>) o URL
--   image_alt    texto alternativo que describe la imagen
--   image_source {titulo, autor, licencia, url} para la atribucion
-- Las imagenes viven en frontend/public/pattern-images/ (no se enlazan a sitios
-- externos para que no se rompan). La migracion deja las columnas vacias: las
-- llena scripts/seed_patterns.py, que el backend corre con --images-only en
-- cada arranque (docker-compose.yml). Fuera de Docker, correrlo a mano.
-- =============================================================================

ALTER TABLE architect_patterns
    ADD COLUMN IF NOT EXISTS image VARCHAR(500),
    ADD COLUMN IF NOT EXISTS image_alt TEXT,
    ADD COLUMN IF NOT EXISTS image_source JSONB;
