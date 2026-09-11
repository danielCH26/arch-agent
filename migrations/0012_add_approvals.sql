-- F05: historial auditable de decisiones sobre la elicitación.
CREATE TABLE IF NOT EXISTS approvals (
    id SERIAL PRIMARY KEY,
    session_id INTEGER REFERENCES sessions(id) ON DELETE CASCADE,
    phase VARCHAR(50) NOT NULL,
    decision VARCHAR(20) NOT NULL,
    feedback TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_approvals_session_phase
    ON approvals (session_id, phase);
