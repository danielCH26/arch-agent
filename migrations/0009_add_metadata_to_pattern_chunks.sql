ALTER TABLE architect_pattern_chunks
    ADD COLUMN IF NOT EXISTS chunk_metadata JSONB;
