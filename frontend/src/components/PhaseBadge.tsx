interface PhaseBadgeProps {
  phase: string | null
  ready?: boolean
}

const phaseColors: Record<string, string> = {
  requirements: 'bg-blue-100 text-blue-800',
  architecture: 'bg-purple-100 text-purple-800',
  implementation: 'bg-yellow-100 text-yellow-800',
  testing: 'bg-orange-100 text-orange-800',
  deployment: 'bg-green-100 text-green-800',
}

export function PhaseBadge({ phase, ready = false }: PhaseBadgeProps) {
  const displayPhase = phase || 'Sin fase'
  const colorClass = phaseColors[displayPhase.toLowerCase()] || 'bg-gray-100 text-gray-800'

  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${colorClass}`}>
      {displayPhase}
      {ready && <span className="ml-1 text-green-600">✓</span>}
    </span>
  )
}
