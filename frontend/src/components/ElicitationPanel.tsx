import { useCallback, useEffect, useRef, useState } from 'react'
import {
  ElicitationState,
  getElicitationState,
  sendElicitationMessage,
} from '../api/elicitation'
import { ApprovalPanel } from './ApprovalPanel'
import { ChatInput } from './ChatInput'
import { ChatHistorySkeleton } from './Skeleton'
import robotAvatar from '../assets/robot-avatar.webp'

// Entrada que el backend agrega al historial cuando el usuario pide cambios
// sobre el resumen ("Solicitar cambios"): no es una pregunta del asistente.
const ADJUSTMENT_MARKER = '(ajuste solicitado por el usuario)'

function AssistantBubble({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-start justify-start gap-2">
      <img src={robotAvatar} alt="" aria-hidden="true" draggable={false} className="mt-1 h-9 w-auto shrink-0 select-none" />
      <div className="max-w-[85%] md:max-w-[70%] whitespace-pre-wrap break-words rounded-2xl rounded-tl-sm border border-sky-200 bg-sky-50 px-4 py-2 text-gray-900 shadow-sm">
        {children}
      </div>
    </div>
  )
}

function UserBubble({ children, label }: { children: React.ReactNode; label?: string }) {
  return (
    <div className="flex justify-end">
      <div className="max-w-[85%] md:max-w-[70%] whitespace-pre-wrap break-words rounded-lg bg-blue-600 px-4 py-2 text-white dark:bg-blue-100">
        {label && <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-blue-100 dark:text-blue-700">{label}</p>}
        {children}
      </div>
    </div>
  )
}

/** El agente aún no dio el siguiente paso (sin pregunta pendiente ni resumen). */
function needsAgentStep(state: ElicitationState): boolean {
  return !state.done && state.question === null && state.history.length > 0
}

interface ElicitationPanelProps {
  projectId: number
  phaseReady: boolean
  onPhaseReady: () => void
}

export function ElicitationPanel({ projectId, phaseReady, onPhaseReady }: ElicitationPanelProps) {
  const [state, setState] = useState<ElicitationState | null>(null)
  const [loading, setLoading] = useState(true)
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')
  const endRef = useRef<HTMLDivElement>(null)

  // Pide al agente el siguiente paso (nueva pregunta o resumen). Se usa al
  // comenzar y cuando el estado quedó sin pregunta pendiente, p. ej. tras
  // "Solicitar cambios" o al recargar a mitad de un paso.
  const advance = useCallback(async () => {
    setError('')
    setSending(true)
    try {
      setState(await sendElicitationMessage(projectId))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error al continuar la elicitación')
    } finally {
      setSending(false)
    }
  }, [projectId])

  // Aplica un estado recibido del backend y, si hace falta, continúa.
  const applyState = useCallback(
    (next: ElicitationState) => {
      setState(next)
      if (needsAgentStep(next)) void advance()
    },
    [advance],
  )

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    getElicitationState(projectId)
      .then((data) => {
        if (!cancelled) applyState(data)
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Error al cargar la elicitación')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [projectId, applyState])

  // Mantener visible la última burbuja.
  useEffect(() => {
    const reduceMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    endRef.current?.scrollIntoView({ behavior: reduceMotion ? 'auto' : 'smooth', block: 'end' })
  }, [state, sending])

  const handleAnswer = async (answer: string): Promise<boolean> => {
    if (sending) return false
    setError('')
    setSending(true)
    try {
      setState(await sendElicitationMessage(projectId, answer))
      return true
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error al enviar la respuesta')
      return false
    } finally {
      setSending(false)
    }
  }

  if (loading) {
    return (
      <div className="h-full overflow-y-auto p-4">
        <ChatHistorySkeleton />
      </div>
    )
  }

  if (!state) {
    return error ? (
      <div className="p-4">
        <div role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</div>
      </div>
    ) : null
  }

  if (state.done && state.resumen) {
    return (
      <div className="h-full overflow-y-auto p-4">
        {phaseReady ? (
          <div className="rounded-lg border border-green-200 bg-green-50 p-4 text-center">
            <p className="font-medium text-gray-900">✓ Resumen aprobado</p>
            <p className="mt-1 text-sm text-gray-600">
              Usa el botón "Avanzar fase" arriba para continuar con la propuesta.
            </p>
          </div>
        ) : (
          <ApprovalPanel
            projectId={projectId}
            resumen={state.resumen}
            onDecided={(result) => {
              if (result.decision === 'approve') {
                onPhaseReady()
              } else {
                // modify: el backend espera que se pida el siguiente paso;
                // reject: la fase vuelve a empezar.
                getElicitationState(projectId)
                  .then(applyState)
                  .catch((err) => setError(err instanceof Error ? err.message : 'Error al cargar la elicitación'))
              }
            }}
          />
        )}
      </div>
    )
  }

  const hasStarted = state.history.length > 0 || state.question !== null

  return (
    <div className="flex h-full flex-col">
      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        <div className="flex flex-col gap-3">
          {/* Lector de pantalla: anuncia solo la pregunta nueva. */}
          <div className="sr-only" aria-live="polite" aria-atomic="true">
            {state.question ? `Pregunta de ArchAgent: ${state.question}` : sending ? 'ArchAgent está pensando…' : ''}
          </div>

          <div className="flex items-center gap-2 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-900">
            <span aria-hidden="true">ℹ️</span>
            <span>Voy a hacerte preguntas para entender tu proyecto</span>
          </div>

          {state.history.map((item, index) =>
            item.pregunta === ADJUSTMENT_MARKER ? (
              <UserBubble key={index} label="Ajuste solicitado">{item.respuesta}</UserBubble>
            ) : (
              <div key={index} className="flex flex-col gap-2">
                <AssistantBubble>{item.pregunta}</AssistantBubble>
                <UserBubble>{item.respuesta}</UserBubble>
              </div>
            ),
          )}

          {state.question && <AssistantBubble>{state.question}</AssistantBubble>}

          {sending && (
            <div className="flex items-start gap-2">
              <img src={robotAvatar} alt="" aria-hidden="true" draggable={false} className="mt-1 h-9 w-auto shrink-0 select-none" />
              <div className="rounded-2xl rounded-tl-sm border border-sky-200 bg-sky-50 px-4 py-3 shadow-sm">
                <div className="flex items-center gap-1">
                  <span className="h-2 w-2 animate-bounce rounded-full bg-gray-400" style={{ animationDelay: '0ms' }} />
                  <span className="h-2 w-2 animate-bounce rounded-full bg-gray-400" style={{ animationDelay: '150ms' }} />
                  <span className="h-2 w-2 animate-bounce rounded-full bg-gray-400" style={{ animationDelay: '300ms' }} />
                </div>
              </div>
            </div>
          )}

          {error && (
            <div role="alert" className="flex flex-wrap items-center gap-3 rounded-lg bg-red-50 p-3 text-sm text-red-700">
              <span>{error}</span>
              {needsAgentStep(state) && !sending && (
                <button type="button" onClick={() => void advance()} className="font-medium underline">
                  Reintentar
                </button>
              )}
            </div>
          )}

          {!hasStarted && (
            <div className="flex justify-center py-4">
              <button
                type="button"
                onClick={() => void advance()}
                disabled={sending}
                className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 dark:hover:bg-solid-blue-700 disabled:opacity-50"
              >
                Comenzar elicitación
              </button>
            </div>
          )}

          <div ref={endRef} />
        </div>
      </div>

      {hasStarted && (
        <ChatInput
          projectId={projectId}
          onSend={handleAnswer}
          disabled={sending || state.question === null}
          allowAttachments={false}
          placeholder="Escribe tu respuesta..."
          ariaLabel="Tu respuesta"
        />
      )}
    </div>
  )
}
