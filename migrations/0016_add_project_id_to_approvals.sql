-- =============================================================================
-- Migration 0016: approvals.project_id (fix de aislamiento entre proyectos)
-- =============================================================================
-- Bug (revisión feature/hu6-diagrama, hallazgo #1): `sessions` es una fila
-- por USUARIO, no por proyecto. `approvals` solo guardaba `session_id`, así
-- que aprobar la propuesta/diagrama del proyecto A hacía que
-- `_load_approved_proposal_doc` (app/api/chat.py) y las lecturas de
-- `elicitation.py` encontraran esa aprobación también para el proyecto B del
-- mismo usuario, nunca aprobado. Esto ya estaba documentado como limitación
-- conocida (QA_feature-hu6-diagrama.md, sección 10) y ahora se corrige.
--
-- Nullable a propósito: additive/idempotente, mismo patrón que 0011
-- (messages.attachments) y 0015 (messages.display_content). Las filas viejas
-- quedan con project_id NULL -- el código nuevo las trata como "sin proyecto
-- conocido" y no las usa como ancla de aprobación (ver
-- record_approval_decision y _load_approved_proposal_doc).
-- =============================================================================

ALTER TABLE approvals
    ADD COLUMN IF NOT EXISTS project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS idx_approvals_project_phase
    ON approvals (project_id, phase);
