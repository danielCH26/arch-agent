-- =============================================================================
-- Migration 0006: crear tabla architect_patterns (RAG de patrones de arquitectura)
-- =============================================================================
-- Issue: Caso de ejemplo (seed)
-- Problema: el modelo ArchitectPattern (app/models/pattern.py) y el seed de
-- patrones (scripts/seed_patterns.py) esperan una tabla `architect_patterns`
-- que todavía no existe en la DB -- nunca se creó ni en el schema base ni
-- en una migración anterior.
--
-- Esta migración crea la tabla de forma idempotente (CREATE TABLE IF NOT
-- EXISTS ya cubre el caso de que se vuelva a correr).
-- =============================================================================
CREATE TABLE IF NOT EXISTS architect_patterns (
    id SERIAL PRIMARY KEY,
    pattern_name VARCHAR(255) NOT NULL,
    category VARCHAR(100),
    description TEXT,
    use_cases TEXT,
    tradeoffs JSONB,
    embedding vector(384),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_architect_patterns_embedding
    ON architect_patterns USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

CREATE INDEX IF NOT EXISTS idx_architect_patterns_category
    ON architect_patterns (category);