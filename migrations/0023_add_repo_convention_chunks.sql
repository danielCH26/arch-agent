-- Convenciones de estructura de repositorio en el RAG (HU F28: árbol de
-- carpetas basado en convenciones y patrones por módulo).
--
-- Tabla propia y no `architect_pattern_chunks`, por las mismas dos razones por
-- las que el catálogo de nube tiene la suya (ver 0022):
--
--   1. Esa tabla cuelga de `pattern_id NOT NULL`; una convención de carpetas de
--      FastAPI no es un patrón de arquitectura y meterla ahí obligaría a
--      inventar filas en `architect_patterns`.
--   2. La historia pide que las convenciones sean una categoría NUEVA del RAG,
--      consultable (y vaciable) sin tocar los patrones.
--
-- Los patrones de nivel `modulo` (Repository, Service Layer, DTO, Unit of
-- Work) NO van acá: son patrones de verdad y viven en `architect_patterns`
-- como los demás, con su campo `level` leído del YAML. Lo único que cambia es
-- quién los consume.
--
-- La dimensión del vector es 384, la de intfloat/multilingual-e5-small, la
-- misma que usa el resto del RAG.

CREATE TABLE IF NOT EXISTS repo_convention_chunks (
    id             SERIAL PRIMARY KEY,
    convention_id  VARCHAR(64)  NOT NULL,
    name           VARCHAR(128) NOT NULL,
    layer          VARCHAR(16)  NOT NULL,
    chunk_text     TEXT         NOT NULL,
    embedding      VECTOR(384),
    chunk_metadata JSONB,
    created_at     TIMESTAMP    DEFAULT NOW(),
    CONSTRAINT uq_repo_convention UNIQUE (convention_id)
);

-- Se consulta filtrando por capa (el generador pide una convención de backend
-- y una de frontend por separado) antes de ordenar por distancia del vector.
CREATE INDEX IF NOT EXISTS idx_repo_convention_chunks_layer
    ON repo_convention_chunks (layer);
