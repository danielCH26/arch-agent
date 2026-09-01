-- Migration 0005: pipeline RAG con patrones de arquitectura y PGVector.

CREATE EXTENSION IF NOT EXISTS vector;

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
    ON architect_patterns(category);

CREATE INDEX IF NOT EXISTS document_chunks_embedding_idx
    ON document_chunks USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

CREATE INDEX IF NOT EXISTS idx_document_chunks_document_id
    ON document_chunks(document_id);
