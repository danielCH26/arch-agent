const PHASE_LABELS: Record<string, string> = {
  requerimientos: 'Requerimientos',
  propuesta: 'Propuesta',
  refinamiento: 'Refinamiento',
  revision: 'Revisión',
}

interface PhaseStepperProps {
  phases: string[]
  currentPhase: string | null
}

export function PhaseStepper({ phases, currentPhase }: PhaseStepperProps) {
  const currentIndex = currentPhase ? phases.indexOf(currentPhase) : -1

  return (
    <div className="flex items-center">
      {phases.map((phase, index) => {
        const isDone = currentIndex >= 0 && index < currentIndex
        const isCurrent = index === currentIndex
        const label = PHASE_LABELS[phase] || phase

        return (
          <div key={phase} className="flex items-center">
            <div className="flex items-center gap-2">
              <span
                className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-semibold ${
                  isDone
                    ? 'bg-green-100 text-green-700'
                    : isCurrent
                      ? 'bg-blue-600 text-white'
                      : 'bg-gray-100 text-gray-400'
                }`}
              >
                {isDone ? '✓' : index + 1}
              </span>
              <span
                className={`text-sm whitespace-nowrap ${
                  isCurrent ? 'font-semibold text-gray-900' : isDone ? 'text-gray-700' : 'text-gray-400'
                }`}
              >
                {label}
              </span>
            </div>
            {index < phases.length - 1 && (
              <div className={`mx-3 h-px w-8 sm:w-12 ${isDone ? 'bg-green-300' : 'bg-gray-200'}`} />
            )}
          </div>
        )
      })}
    </div>
  )
}
