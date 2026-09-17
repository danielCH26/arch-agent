-- =============================================================================
-- Migration 0015: messages.display_content (fix de fondo para "Solicitar
-- cambios" sobre el diagrama — QA_feature-hu6-diagrama, seccion 0 punto 7)
-- =============================================================================
-- Mismo patron que la migracion 0011 (messages.attachments): columna
-- nullable, additive, idempotente. Re-correrla contra una DB que ya la
-- tiene es un no-op (ADD COLUMN IF NOT EXISTS).
--
-- Guarda lo que el USUARIO vio/escribio en su propia burbuja cuando difiere
-- del texto real que se le manda al agente (``messages.content``). Hoy el
-- unico caso es "Solicitar cambios" sobre un diagrama: el prompt que recibe
-- el LLM incluye instrucciones + el Mermaid anterior, pero el usuario solo
-- escribio su feedback. NULL en el resto de los mensajes (la inmensa
-- mayoria) -- GET /api/chat/history resuelve el fallback
-- ``display_content or content`` (ver app/api/chat.py).
-- =============================================================================

ALTER TABLE messages
    ADD COLUMN IF NOT EXISTS display_content TEXT NULL;
