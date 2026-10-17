import { useNavigate } from 'react-router-dom'
import { useDialog } from '../hooks/useDialog'
import { RobotGreeter } from './RobotGreeter'

interface ProjectCompletedDialogProps {
  open: boolean
  projectName?: string | null
  onClose: () => void
}

const PHASES_DONE = ['Requerimientos', 'Propuesta', 'Refinamiento', 'Revisión']

/**
 * Cierre del proyecto: el robot felicita al usuario por completar todas las
 * fases y le ofrece empezar otro proyecto o volver al inicio.
 */
export function ProjectCompletedDialog({ open, projectName, onClose }: ProjectCompletedDialogProps) {
  const navigate = useNavigate()
  const dialogRef = useDialog({ open, onClose })

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" role="presentation">
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="project-completed-title"
        data-testid="project-completed"
        className="w-full max-w-lg rounded-2xl bg-white p-6 text-center shadow-xl dark:bg-gray-900"
      >
        <div className="flex justify-center">
          <RobotGreeter />
        </div>
        <h2 id="project-completed-title" className="mt-4 text-xl font-semibold text-gray-900 dark:text-gray-100">
          ¡Felicidades! Completaste todas las fases 🎉
        </h2>
        <p className="mt-2 text-sm text-gray-600 dark:text-gray-300">
          {projectName ? <>La arquitectura de <strong>{projectName}</strong> quedó lista.</> : 'La arquitectura de tu proyecto quedó lista.'}{' '}
          Tienes el ADR con todas las decisiones y una guía para empezar a construir.
        </p>
        <ul className="mt-4 flex flex-wrap justify-center gap-2 text-xs" aria-label="Fases completadas">
          {PHASES_DONE.map((phase) => (
            <li key={phase} className="rounded-full bg-green-50 px-3 py-1 font-medium text-green-800">
              ✓ {phase}
            </li>
          ))}
        </ul>
        <div className="mt-6 flex flex-col gap-2 sm:flex-row sm:justify-center">
          <button
            type="button"
            data-testid="completed-new-project"
            onClick={() => navigate('/projects', { state: { openCreate: true } })}
            className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700"
          >
            Crear otro proyecto
          </button>
          <button
            type="button"
            data-testid="completed-go-home"
            onClick={() => navigate('/projects')}
            className="rounded-lg border border-gray-300 px-4 py-2 text-sm text-gray-700 hover:bg-gray-100 dark:border-gray-600 dark:text-gray-200 dark:hover:bg-gray-800"
          >
            Ir al inicio
          </button>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg px-4 py-2 text-sm text-gray-600 underline hover:text-gray-900 dark:text-gray-400"
          >
            Seguir viendo el ADR
          </button>
        </div>
      </div>
    </div>
  )
}
