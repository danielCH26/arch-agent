-- =============================================================================
-- Migration 0007: crear tabla approvals (Feature 3 / issue de elicitación)
-- =============================================================================
-- Issue: [F05] Elicitación guiada + aprobación
-- Contexto: la tabla approvals no existía en ningún lado (ni schema.sql ni
-- una migración anterior), aunque el criterio de aceptación del issue exige
-- registrar ahí las decisiones de aprobar/modificar/rechazar (mismo
-- mecanismo de Feature 3: Refinamiento y validación por etapas, HU8).
--
-- Diseño: session_id (no project_id) porque sessions es la fila con el
-- estado real (engram_state); una sesión puede tener varias decisiones a
-- lo largo del tiempo para la misma fase (ej. rechazar y luego aprobar),
-- así que NO hay UNIQUE(session_id, phase) -- se guarda el historial
-- completo, no solo la última decisión.
-- =============================================================================
CREATE TABLE IF NOT EXISTS approvals (
    id SERIAL PRIMARY KEY,
    session_id INTEGER REFERENCES sessions(id) ON DELETE CASCADE,
    phase VARCHAR(50) NOT NULL,
    decision VARCHAR(20) NOT NULL,  -- 'approved' | 'modified' | 'rejected'
    feedback TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_approvals_session_phase
    ON approvals (session_id, phase);
