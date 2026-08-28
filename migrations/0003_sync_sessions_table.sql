-- =============================================================================
-- Migration 0003: sincronizar tabla sessions con modelo UserSession
-- =============================================================================
-- Issue: detectado durante testing de HU13
-- Problema: el modelo UserSession (app/models/session.py) espera columnas
-- (user_id, active_phase, engram_state, last_seen_at) que no existen en la tabla
-- `sessions` actual de la DB.
--
-- Esta migración agrega las columnas faltantes de forma idempotente.
-- =============================================================================

-- 1. Agregar user_id (FK a users, UNIQUE por user)
ALTER TABLE sessions
    ADD COLUMN IF NOT EXISTS user_id INTEGER;

-- 2. Agregar active_phase
ALTER TABLE sessions
    ADD COLUMN IF NOT EXISTS active_phase VARCHAR(50);

-- 3. Agregar engram_state (JSONB)
ALTER TABLE sessions
    ADD COLUMN IF NOT EXISTS engram_state JSONB;

-- 4. Agregar last_seen_at
ALTER TABLE sessions
    ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMP;

-- 5. Crear FK a users si no existe
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'sessions_user_id_fkey'
    ) THEN
        ALTER TABLE sessions
            ADD CONSTRAINT sessions_user_id_fkey
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;
    END IF;
END $$;

-- 6. Crear UNIQUE constraint (un UserSession por user)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'uniq_sessions_user_id'
    ) THEN
        ALTER TABLE sessions
            ADD CONSTRAINT uniq_sessions_user_id UNIQUE (user_id);
    END IF;
END $$;

-- 7. Crear índice en user_id (idempotente)
CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions (user_id);
