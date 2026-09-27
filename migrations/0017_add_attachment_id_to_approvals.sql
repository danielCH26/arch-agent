-- =============================================================================
-- Migration 0017: approvals.attachment_id (decisión POR diagrama)
-- =============================================================================
-- Bug (QA HU6): las decisiones sobre un diagrama (aprobar / rechazar / pedir
-- cambios) se guardaban solo a nivel de proyecto (phase="diagram"), sin saber
-- a QUÉ diagrama se referían. Consecuencias:
--   * el chat no podía recordar que un diagrama ya estaba decidido: tras un
--     F5 volvían a aparecer los tres botones;
--   * el panel de historial ofrecía decidir sobre "el diagrama actual" aunque
--     ya se hubiera decidido en el chat.
--
-- `attachment_id` es el UUID del adjunto (messages.attachments[].id, el mismo
-- que va firmado en la URL de la imagen). Nullable a propósito: additive /
-- idempotente, mismo patrón que 0011, 0015 y 0016. Las filas anteriores (y
-- las decisiones de otras fases) quedan en NULL.
-- =============================================================================

ALTER TABLE approvals
    ADD COLUMN IF NOT EXISTS attachment_id VARCHAR(64);

CREATE INDEX IF NOT EXISTS idx_approvals_attachment_id
    ON approvals (attachment_id);
