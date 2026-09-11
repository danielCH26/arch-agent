-- F05: restringe los valores persistidos de las decisiones de elicitación.
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
