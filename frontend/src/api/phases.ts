// Fases del flujo, en el mismo orden que AVAILABLE_PHASES en app/api/projects.py.
// Cada una tiene su pantalla en el front:
//   requerimientos -> elicitación (preguntas + resumen a aprobar)
//   propuesta      -> tarjeta de propuesta de arquitectura
//   refinamiento   -> genera el DIAGRAMA (Mermaid) de la propuesta aprobada y permite
//                     refinarlo; el letrero muestra el nombre real de la fase
//   revision       -> última fase (sin pantalla propia todavía)
export const PHASES = ['requerimientos', 'propuesta', 'refinamiento', 'revision'] as const

export const PHASE_LABELS: Record<string, string> = {
  requerimientos: 'Requerimientos',
  propuesta: 'Propuesta',
  refinamiento: 'Refinamiento',
  // Valores heredados que todavía pueden existir en proyectos creados antes
  // de consolidar el nombre de la fase. Ambos usan la vista de refinamiento.
  diagram: 'Refinamiento',
  diagrama: 'Refinamiento',
  revision: 'Revisión',
}

const REFINEMENT_PHASES = new Set(['refinamiento', 'diagram', 'diagrama'])

export function isRefinementPhase(phase: string | null | undefined): boolean {
  return REFINEMENT_PHASES.has((phase ?? '').toLowerCase())
}

export function phaseLabel(phase: string | null | undefined): string {
  if (!phase) return 'Sin fase'
  return PHASE_LABELS[phase.toLowerCase()] ?? phase
}

/** Siguiente fase del flujo, o null si ya es la última / no se reconoce. */
export function nextPhase(phase: string | null | undefined): string | null {
  const normalized = isRefinementPhase(phase) ? 'refinamiento' : (phase ?? '').toLowerCase()
  const idx = PHASES.indexOf(normalized as (typeof PHASES)[number])
  if (idx === -1 || idx === PHASES.length - 1) return null
  return PHASES[idx + 1]
}
