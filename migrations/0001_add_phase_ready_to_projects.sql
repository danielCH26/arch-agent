-- Migración 0001: agrega la columna que controla si la fase actual del
-- proyecto ya está lista para avanzar a la siguiente.

ALTER TABLE projects
    ADD COLUMN IF NOT EXISTS phase_ready BOOLEAN NOT NULL DEFAULT FALSE;
