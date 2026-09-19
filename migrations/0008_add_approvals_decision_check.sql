-- =============================================================================
-- Migration 0008: CHECK constraint en approvals.decision
-- =============================================================================
-- Sugerido en revisión de PR #63: blindar a nivel de BD el enum de
-- decisiones, no depender solo de la validación de Pydantic.
--
-- Nota: la sugerencia original proponía CHECK (decision IN
-- ('approve','modify','reject')) -- esos son los verbos que acepta el
-- body del endpoint (ElicitationDecisionIn.decision), pero NO lo que se
-- guarda realmente en la columna. app/api/elicitation.py mapea esos
-- verbos a DECISION_TO_DB = {"approve": "approved", "modify": "modified",
-- "reject": "rejected"} antes de insertar -- y scripts/seed_example.py
-- también inserta 'approved' directamente. El CHECK usa esos valores
-- reales (participio, en pasado), no los del body del request.
-- =============================================================================
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'chk_approvals_decision'
    ) THEN
        ALTER TABLE approvals
            ADD CONSTRAINT chk_approvals_decision
            CHECK (decision IN ('approved', 'modified', 'rejected'));
    END IF;
END $$;
