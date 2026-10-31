import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { ApiConflictError, decidePhase } from '../api/approvals'
import { ApiError } from '../api/client'
import { advancePhase, getProject, getProjectPhase, PhaseInfo, Project } from '../api/projects'
import { ChatWindow } from '../components/ChatWindow'
import { DiagramHistoryPanel } from '../components/DiagramHistoryPanel'
import { ElicitationPanel } from '../components/ElicitationPanel'
import { PhaseStepper } from '../components/PhaseStepper'
import { projectsStore } from '../stores/projectsStore'
import { projectUnavailableMessage } from '../stores/authStore'

const ELICITATION_PHASE = 'requerimientos'
const REFINEMENT_PHASE = 'refinamiento'

/**
 * Se vuelve a montar al cambiar de proyecto (`key`), para que ningún render
 * combine el `projectId` nuevo con la fase o el proyecto anteriores.
 */
export function ChatPage() {
  const { id } = useParams<{ id: string }>()
  return <ChatPageContent key={id} />
}

function ChatPageContent() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const projectId = Number(id)
  const [project, setProject] = useState<Project | null>(null)
  const [phase, setPhase] = useState<PhaseInfo | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [phaseActionError, setPhaseActionError] = useState('')
  const [phaseActionLoading, setPhaseActionLoading] = useState(false)
  const [diagramHistoryOpen, setDiagramHistoryOpen] = useState(false)
  // Las respuestas que llegan después de salir de este proyecto se descartan.
  const unmounted = useRef(false)
  useEffect(() => () => {
    unmounted.current = true
  }, [])

  useEffect(() => {
    let cancelled = false

    if (!projectId || isNaN(projectId)) {
      setError('ID de proyecto inválido')
      setLoading(false)
      return
    }

    Promise.all([getProject(projectId), getProjectPhase(projectId)])
      .then(([projectData, phaseData]) => {
        if (cancelled) return
        setProject(projectData)
        setPhase(phaseData)
        // Setear el proyecto activo en el store global para que el sidebar
        // muestre los links a Chat / Documentos / Configuración.
        projectsStore.getState().setCurrentProject(projectData)
      })
      .catch((err) => {
        if (cancelled) return
        // Proyecto ajeno o eliminado: volver a "Mis proyectos" con un aviso.
        if (err instanceof ApiError && (err.status === 403 || err.status === 404)) {
          projectsStore.getState().setCurrentProject(null)
          navigate('/projects', {
            replace: true,
            state: { message: projectUnavailableMessage() },
          })
          return
        }
        setError(err instanceof Error ? err.message : 'Error al cargar el proyecto')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [projectId, navigate])

  const refreshAfterPhaseChange = useCallback(async () => {
    const [projectData, phaseData] = await Promise.all([getProject(projectId), getProjectPhase(projectId)])
    if (unmounted.current) return
    setProject(projectData)
    setPhase(phaseData)
    projectsStore.getState().setCurrentProject(projectData)
  }, [projectId])

  // Refinamiento tiene DOS pasos: aprobar la arquitectura y después llevarla
  // a una nube. Aprobar el diagrama ya NO cierra la fase -- solo refresca,
  // para que aparezca el panel de despliegue. La fase la cierra el paso de
  // la nube (`handleDeploymentApproved`).
  //
  // La decisión sobre el diagrama en sí ya la registró <MessageBubble> con
  // `/api/diagrams/decision`; eso no toca la fase.
  const handleDiagramApproved = async () => {
    setPhaseActionError('')
    await refreshAfterPhaseChange()
  }

  // Cierra Refinamiento: se llama al aprobar el diagrama de DESPLIEGUE, que
  // es el último paso de la fase. Hasta aquí `phase_ready` sigue en false y
  // "Avanzar fase" no aparece, así que no se puede saltar la nube.
  // RELANZA si falla. El panel de despliegue necesita enterarse: la decisión
  // sobre el diagrama ya quedó registrada y el backend responde 409 si se
  // repite, así que el reintento tiene que ser solo de ESTO, y el panel es
  // quien ofrece ese botón. Si el error se tragara aquí, el botón Aprobar ya
  // no estaría y el proyecto se quedaría trabado en Refinamiento.
  const handleDeploymentApproved = async () => {
    setPhaseActionError('')
    setPhaseActionLoading(true)
    try {
      try {
        await decidePhase(projectId, REFINEMENT_PHASE, { action: 'approve' })
      } catch (err) {
        // Ya aprobada (p. ej. desde otra pestaña): no es un error.
        if (!(err instanceof ApiConflictError)) throw err
      }
      await refreshAfterPhaseChange()
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
      <div role="alert" className="p-4 bg-red-50 text-red-700 rounded-lg">
        {error}
      </div>
    )
  }

  const isElicitationPhase = phase?.current_phase === ELICITATION_PHASE

  // El historial de Diagramas solo se ofrece desde Refinamiento: antes de esa
  // fase todavía no se ha generado ninguno y el botón llevaba a un panel
  // vacío. Se compara por posición dentro de `available_phases` en vez de por
  // nombre, para no depender de cómo se llamen las fases intermedias; si
  // Refinamiento no estuviera en la lista, se cae al criterio anterior.
  const phaseIndex = phase ? phase.available_phases.indexOf(phase.current_phase ?? '') : -1
  const refinementIndex = phase ? phase.available_phases.indexOf(REFINEMENT_PHASE) : -1
  const showDiagramHistory =
    refinementIndex >= 0 ? phaseIndex >= refinementIndex : !isElicitationPhase
  // En la última fase no hay a dónde avanzar. Con HU10 se completa aprobando
  // la fase `final` desde <PhaseActions> (mark-ready se retiró, REQ-SA-23).
  const isLastPhase =
    !!phase &&
    phase.available_phases.length > 0 &&
    phase.available_phases.indexOf(phase.current_phase ?? '') === phase.available_phases.length - 1

  return (
    <div className="h-full flex flex-col">
      <div className="border-b border-gray-200 px-4 py-3 bg-white">
        <h1 className="font-display truncate text-lg font-semibold text-gray-900 md:text-xl">{project?.name}</h1>
        {phase && (
          <div className="mt-2 overflow-x-auto">
            <PhaseStepper phases={phase.available_phases} currentPhase={phase.current_phase} />
          </div>
        )}
      </div>

      {phase && (
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-gray-200 bg-gray-50 px-4 py-2">
          <span className="text-sm text-gray-600">
            {isLastPhase
              ? phase.phase_ready
                ? 'Proyecto completado.'
                : 'Última fase: apruébala en el panel de decisión para completar el proyecto.'
              : phase.phase_ready
                ? 'Fase lista para avanzar.'
                : 'Fase en progreso.'}
          </span>
          <div className="flex flex-wrap gap-2">
            {showDiagramHistory && (
              <button
                type="button"
                onClick={() => setDiagramHistoryOpen(true)}
                className="inline-flex items-center gap-1.5 rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-100"
              >
                <svg aria-hidden="true" className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M3.75 6A2.25 2.25 0 016 3.75h2.25A2.25 2.25 0 0110.5 6v2.25a2.25 2.25 0 01-2.25 2.25H6a2.25 2.25 0 01-2.25-2.25V6zM3.75 15.75A2.25 2.25 0 016 13.5h2.25a2.25 2.25 0 012.25 2.25V18a2.25 2.25 0 01-2.25 2.25H6A2.25 2.25 0 013.75 18v-2.25zM13.5 6a2.25 2.25 0 012.25-2.25H18A2.25 2.25 0 0120.25 6v2.25A2.25 2.25 0 0118 10.5h-2.25a2.25 2.25 0 01-2.25-2.25V6zM13.5 15.75a2.25 2.25 0 012.25-2.25H18a2.25 2.25 0 012.25 2.25V18A2.25 2.25 0 0118 20.25h-2.25A2.25 2.25 0 0113.5 18v-2.25z" />
                </svg>
                Diagramas
              </button>
            )}
            {/* HU10 (REQ-SA-23): "Marcar fase como lista" se retiró (mark-ready
                responde 404). La APROBACIÓN vive en el panel de cada fase
                (<ProposalCard>, los botones del diagrama, <PhaseActions>),
                pero "Avanzar" vive ACÁ: abajo del todo, al final del chat,
                quedaba fuera de la vista y había que buscarlo. Un único botón,
                siempre en el mismo sitio y junto al "Fase lista para avanzar".
                `phaseReady={false}` en <PhaseActions> evita el duplicado. */}
            {(isElicitationPhase || (!isLastPhase && phase.phase_ready)) && (
              <button
                type="button"
                onClick={handleAdvance}
                disabled={phaseActionLoading || !phase.phase_ready}
                className="rounded-lg bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 dark:hover:bg-solid-blue-700 disabled:cursor-not-allowed disabled:bg-gray-300"
              >
                Avanzar fase →
              </button>
            )}
          </div>
        </div>
      )}
      {phaseActionError && (
        <div role="alert" className="px-4 py-2 text-sm text-red-700 bg-red-50">{phaseActionError}</div>
      )}

      <div className="flex-1 min-h-0">
        {isElicitationPhase ? (
          <div className="h-full">
            <ElicitationPanel
              projectId={projectId}
              phaseReady={phase?.phase_ready ?? false}
              onPhaseReady={refreshAfterPhaseChange}
            />
          </div>
        ) : (
          <div className="h-full">
            <ChatWindow
              projectId={projectId}
              phase={phase?.current_phase}
              onProposalPhaseChanged={refreshAfterPhaseChange}
              onDiagramApproved={handleDiagramApproved}
              onDeploymentApproved={handleDeploymentApproved}
              onProjectCompleted={refreshAfterPhaseChange}
            />
          </div>
        )}
      </div>
      <DiagramHistoryPanel
        projectId={projectId}
        open={diagramHistoryOpen}
        onClose={() => setDiagramHistoryOpen(false)}
      />
    </div>
  )
}
