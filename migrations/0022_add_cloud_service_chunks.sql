-- Catálogo de servicios de nube en el RAG (HU: diagrama de despliegue).
--
-- Tabla propia y no `architect_pattern_chunks` por dos razones:
--   1. Esa tabla cuelga de `pattern_id NOT NULL`; un servicio de nube no es
--      un patrón de arquitectura y meterlo ahí obligaría a inventar filas en
--      `architect_patterns`.
--   2. La historia pide que el catálogo sea una categoría NUEVA del RAG,
--      separada de la base de patrones, para poder consultarlo (y vaciarlo)
--      sin tocar los patrones.
--
-- La dimensión del vector es 384, la de intfloat/multilingual-e5-small, la
-- misma que usa el resto del RAG.

CREATE TABLE IF NOT EXISTS cloud_service_chunks (
    id            SERIAL PRIMARY KEY,
    provider      VARCHAR(32)  NOT NULL,
    service_id    VARCHAR(64)  NOT NULL,
    service_name  VARCHAR(128) NOT NULL,
    category      VARCHAR(32)  NOT NULL,
    chunk_text    TEXT         NOT NULL,
    embedding     VECTOR(384),
    chunk_metadata JSONB,
    created_at    TIMESTAMP    DEFAULT NOW(),
    CONSTRAINT uq_cloud_service UNIQUE (provider, service_id)
);

-- Se consulta casi siempre filtrando por proveedor (el usuario ya eligió
-- una nube) antes de ordenar por distancia del vector.
CREATE INDEX IF NOT EXISTS idx_cloud_service_chunks_provider
    ON cloud_service_chunks (provider);

CREATE INDEX IF NOT EXISTS idx_cloud_service_chunks_category
    ON cloud_service_chunks (provider, category);
