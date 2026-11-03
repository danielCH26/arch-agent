// Nombre de cada fase tal como lo lee el usuario (con tildes). La clave es la
// que usa la API (`revision`); en pantalla nunca se muestra la clave cruda.
// Mismos nombres que PHASE_LABELS del backend.
export const PHASE_LABELS: Record<string, string> = {
  requerimientos: 'Requerimientos',
  propuesta: 'Propuesta',
  refinamiento: 'Refinamiento',
  revision: 'Revisión',
  // HU10: quinta fase.
  final: 'Cierre',
}

export function phaseLabel(phase: string | null | undefined): string {
  return (phase && PHASE_LABELS[phase]) || phase || ''
}
