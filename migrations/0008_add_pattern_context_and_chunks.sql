ALTER TABLE architect_patterns
    ADD COLUMN IF NOT EXISTS when_not_to_use TEXT,
    ADD COLUMN IF NOT EXISTS decision_signals JSONB;

CREATE TABLE IF NOT EXISTS architect_pattern_chunks (
    id SERIAL PRIMARY KEY,
    pattern_id INTEGER NOT NULL REFERENCES architect_patterns(id) ON DELETE CASCADE,
    chunk_type VARCHAR(50) NOT NULL,
    chunk_text TEXT NOT NULL,
    embedding vector(384),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_pattern_chunks_embedding
    ON architect_pattern_chunks USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

CREATE INDEX IF NOT EXISTS idx_pattern_chunks_pattern_id
    ON architect_pattern_chunks (pattern_id);
