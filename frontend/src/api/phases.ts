// Fases del flujo, en el mismo orden que AVAILABLE_PHASES en app/api/projects.py.
// Cada una tiene su pantalla en el front:
//   requerimientos -> elicitación (preguntas + resumen a aprobar)
//   propuesta      -> tarjeta de propuesta de arquitectura
//   refinamiento   -> chat que genera el DIAGRAMA (Mermaid)
//   revision       -> última fase (sin pantalla propia todavía)
export const PHASES = ['requerimientos', 'propuesta', 'refinamiento', 'revision'] as const

export const PHASE_LABELS: Record<string, string> = {
  requerimientos: 'Requerimientos',
  propuesta: 'Propuesta',
  refinamiento: 'Diagrama',
  revision: 'Revisión',
}

export function phaseLabel(phase: string | null | undefined): string {
  if (!phase) return 'Sin fase'
  return PHASE_LABELS[phase.toLowerCase()] ?? phase
}

/** Siguiente fase del flujo, o null si ya es la última / no se reconoce. */
export function nextPhase(phase: string | null | undefined): string | null {
  const idx = PHASES.indexOf((phase ?? '').toLowerCase() as (typeof PHASES)[number])
  if (idx === -1 || idx === PHASES.length - 1) return null
  return PHASES[idx + 1]
}
