-- =============================================================================
-- Migration 0021: approvals — deshacer el backfill amplio de la 0020 vieja
-- =============================================================================
-- Contexto: la primera versión de 0020 rellenaba ``approvals.project_id``
-- desde ``sessions.project_id`` para TODOS los usuarios. ``sessions`` tiene
-- una fila por usuario y su ``project_id`` es el último proyecto abierto, así
-- que en usuarios con varios proyectos cada aprobación legacy quedó anclada a
-- ese último proyecto (review PR #105). La 0020 actual limita el backfill a
-- usuarios con un solo proyecto, pero ``run_migrations.py`` registra cada
-- migración por nombre de archivo: una base que ya corrió la versión vieja
-- no la vuelve a correr y las filas mal asignadas siguen ahí.
--
-- Qué hace: devuelve a NULL el ``project_id`` de las filas legacy de usuarios
-- con más de un proyecto. "Legacy" = creada ANTES de aplicar la 0016, que es
-- la migración que agregó la columna: esas filas nacieron sin project_id, así
-- que si hoy tienen uno vino de un backfill, y para usuarios multi-proyecto
-- ese valor no es confiable. NULL es el estado que la 0020 actual deja para
-- estos casos ("proyecto desconocido", REQ-SA-27; triage manual).
--
-- No toca:
--   * filas escritas por la aplicación después de la 0016 (traen project_id
--     desde el INSERT);
--   * usuarios con un solo proyecto (el backfill era correcto para ellos);
--   * bases donde schema_migrations no registra la 0016 (p. ej. creadas desde
--     schema.sql): la subconsulta da NULL y el WHERE no matchea ninguna fila.
--
-- En una base que corrió la 0020 actual (o una base nueva) es un no-op.
-- Idempotente: correrla dos veces no cambia nada la segunda vez.
--
-- Antes de aplicarla en una base compartida conviene ver cuántas filas toca:
--
--   SELECT count(*)
--   FROM approvals a JOIN sessions s ON s.id = a.session_id
--   WHERE a.project_id IS NOT NULL
--     AND a.created_at < (SELECT applied_at FROM schema_migrations
--                         WHERE filename = '0016_add_project_id_to_approvals.sql')
--     AND (SELECT count(*) FROM projects p WHERE p.user_id = s.user_id) > 1;
--
-- Rollback: no hay vuelta automática (el valor anterior era un dato erróneo).
-- =============================================================================

UPDATE approvals a
SET project_id = NULL
FROM sessions s
WHERE a.session_id = s.id
  AND a.project_id IS NOT NULL
  AND a.created_at < (
      SELECT applied_at
      FROM schema_migrations
      WHERE filename = '0016_add_project_id_to_approvals.sql'
  )
  AND (SELECT count(*) FROM projects p WHERE p.user_id = s.user_id) > 1;
