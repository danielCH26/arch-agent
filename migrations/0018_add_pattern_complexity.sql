-- =============================================================================
-- Migration 0018: architect_patterns.complexity
-- =============================================================================
-- Problema: la propuesta elegia el patron principal solo por similitud
-- semantica, sin considerar cuanta complejidad operativa exige. Proyectos
-- chicos terminaban con patrones pesados (BFF, microservicios...).
--
-- `complexity` = complejidad operativa y de equipo que exige el patron:
-- 'baja' | 'media' | 'alta' (se llena desde data/patterns/*.yaml con
-- scripts/seed_patterns.py). Nullable y aditiva: los patrones sin valor no
-- se penalizan al reordenar candidatos.
-- =============================================================================

ALTER TABLE architect_patterns
    ADD COLUMN IF NOT EXISTS complexity VARCHAR(10);
