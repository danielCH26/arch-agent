import { phaseLabel } from '../api/phases'

interface PhaseBadgeProps {
  phase: string | null
  ready?: boolean
}

// Las fases reales del backend (ver api/phases.ts). Antes las claves eran
// en inglés (requirements/architecture/...) y no coincidían con ninguna fase.
const phaseColors: Record<string, string> = {
  requerimientos: 'bg-blue-100 text-blue-800',
  propuesta: 'bg-purple-100 text-purple-800',
  refinamiento: 'bg-yellow-100 text-yellow-800',
  revision: 'bg-green-100 text-green-800',
}

export function PhaseBadge({ phase, ready = false }: PhaseBadgeProps) {
  const displayPhase = phase ? phaseLabel(phase) : 'Sin fase'
  const colorClass = phaseColors[(phase || '').toLowerCase()] || 'bg-gray-100 text-gray-800'

  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${colorClass}`}>
      {displayPhase}
      {ready && <span className="ml-1 text-green-600">✓</span>}
    </span>
  )
}
