import { useCallback, useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { advancePhase, getProject, getProjectPhase, markReady, PhaseInfo, Project } from '../api/projects'
import { ChatWindow } from '../components/ChatWindow'
import { ElicitationPanel } from '../components/ElicitationPanel'
import { PhaseStepper } from '../components/PhaseStepper'
import { projectsStore } from '../stores/projectsStore'

const ELICITATION_PHASE = 'requerimientos'

export function ChatPage() {
  const { id } = useParams<{ id: string }>()
  const projectId = Number(id)
  const [project, setProject] = useState<Project | null>(null)
  const [phase, setPhase] = useState<PhaseInfo | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [phaseActionError, setPhaseActionError] = useState('')
  const [phaseActionLoading, setPhaseActionLoading] = useState(false)

  useEffect(() => {
    if (!projectId || isNaN(projectId)) {
      setError('ID de proyecto inválido')
      setLoading(false)
      return
    }

    Promise.all([getProject(projectId), getProjectPhase(projectId)])
      .then(([projectData, phaseData]) => {
        setProject(projectData)
        setPhase(phaseData)
        // Setear el proyecto activo en el store global para que el sidebar
        // muestre los links a Chat / Documentos / Configuración.
        projectsStore.getState().setCurrentProject(projectData)
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : 'Error al cargar el proyecto')
      })
      .finally(() => {
        setLoading(false)
      })
  }, [projectId])

  const refreshAfterPhaseChange = useCallback(async () => {
    const [projectData, phaseData] = await Promise.all([getProject(projectId), getProjectPhase(projectId)])
    setProject(projectData)
    setPhase(phaseData)
    projectsStore.getState().setCurrentProject(projectData)
  }, [projectId])

  const handleMarkReady = async () => {
    setPhaseActionError('')
    setPhaseActionLoading(true)
    try {
      await markReady(projectId)
      await refreshAfterPhaseChange()
    } catch (err) {
      setPhaseActionError(err instanceof Error ? err.message : 'Error al marcar la fase como lista')
    } finally {
      setPhaseActionLoading(false)
    }
  }

  const handleAdvance = async () => {
    setPhaseActionError('')
    setPhaseActionLoading(true)
    try {
      await advancePhase(projectId)
      await refreshAfterPhaseChange()
    } catch (err) {
      setPhaseActionError(err instanceof Error ? err.message : 'Error al avanzar de fase')
    } finally {
      setPhaseActionLoading(false)
    }
  }

  if (loading) {
    return (
      <div className="flex justify-center py-12">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="p-4 bg-red-50 text-red-700 rounded-lg">
        {error}
      </div>
    )
  }

  const isElicitationPhase = phase?.current_phase === ELICITATION_PHASE

  return (
    <div className="h-full flex flex-col">
      <div className="border-b border-gray-200 px-4 py-3 bg-white">
        <h1 className="text-xl font-semibold text-gray-900">{project?.name}</h1>
        {phase && (
          <div className="mt-2 overflow-x-auto">
            <PhaseStepper phases={phase.available_phases} currentPhase={phase.current_phase} />
          </div>
        )}
      </div>

      {phase && (
        <div className="flex items-center justify-between gap-3 border-b border-gray-200 bg-gray-50 px-4 py-2">
          <span className="text-sm text-gray-600">
            {phase.phase_ready ? 'Fase lista para avanzar.' : 'Fase en progreso.'}
          </span>
          <div className="flex gap-2">
            {!isElicitationPhase && !phase.phase_ready && (
              <button
                type="button"
                onClick={handleMarkReady}
                disabled={phaseActionLoading}
                className="rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-100 disabled:opacity-50"
              >
                Marcar fase como lista
              </button>
            )}
            <button
              type="button"
              onClick={handleAdvance}
              disabled={phaseActionLoading || !phase.phase_ready}
              className="rounded-lg bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            >
              Avanzar fase →
            </button>
          </div>
        </div>
      )}
      {phaseActionError && (
        <div className="px-4 py-2 text-sm text-red-700 bg-red-50">{phaseActionError}</div>
      )}

      <div className="flex-1 min-h-0">
        {isElicitationPhase ? (
          <div className="mx-auto h-full max-w-2xl overflow-y-auto p-4">
            <ElicitationPanel
              projectId={projectId}
              phaseReady={phase?.phase_ready ?? false}
              onPhaseReady={refreshAfterPhaseChange}
            />
          </div>
        ) : (
          <div className="h-full">
            <ChatWindow projectId={projectId} />
          </div>
        )}
      </div>
    </div>
  )
}
