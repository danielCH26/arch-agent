import { useCallback, useEffect, useRef, useState } from 'react'
import {
  getElicitationState,
  sendElicitationMessage,
  submitElicitationDecision,
  type ElicitationDecision,
  type ElicitationState,
} from '../api/chat'
import { nextPhase, phaseLabel } from '../api/phases'
import { chatStore } from '../stores/chatStore'
import { projectsStore } from '../stores/projectsStore'
import { proposalsStore } from '../stores/proposalsStore'
import { ChatInput } from './ChatInput'
import { MessageBubble } from './MessageBubble'
import { ProposalCard } from './proposals/ProposalCard'

interface ChatWindowProps {
  projectId: number
  phase?: string | null
  /** phase_ready del proyecto: la fase actual ya está aprobada y se puede avanzar. */
  phaseReady?: boolean
  /** Pide al padre que vuelva a cargar el proyecto (fase / phase_ready cambiaron). */
  onProjectUpdated?: () => void | Promise<void>
  /** Avanza a la siguiente fase (POST /advance + recarga del proyecto). */
  onAdvance?: () => Promise<void>
}

function SummaryList({ items }: { items: unknown }) {
  const values = Array.isArray(items) ? items : []
  if (!values.length) return <p className="text-sm italic text-gray-500">No especificado</p>
  return (
    <ul className="list-disc space-y-0.5 pl-5 text-sm text-gray-800">
      {values.map((item, index) => <li key={index}>{String(item)}</li>)}
    </ul>
  )
}

function SummaryView({ resumen }: { resumen: Record<string, unknown> }) {
  return (
    <div className="rounded-lg bg-gray-100 p-4 text-gray-900">
      <h2 className="text-lg font-bold">Resumen de requerimientos para validar</h2>
      <div className="mt-3 space-y-1 text-sm">
        <p><span className="font-semibold">Problema:</span> {String(resumen.problema || 'No especificado')}</p>
        <p><span className="font-semibold">Usuarios:</span> {String(resumen.usuarios || 'No especificado')}</p>
      </div>
      <div className="mt-3">
        <h3 className="text-base font-bold">Funcionalidades</h3>
        <SummaryList items={resumen.funcionalidades} />
      </div>
      <div className="mt-3">
        <h3 className="text-base font-bold">Restricciones</h3>
        <SummaryList items={resumen.restricciones} />
      </div>
      <div className="mt-3">
        <h3 className="text-base font-bold">Calidad</h3>
        <SummaryList items={resumen.calidad} />
      </div>
    </div>
  )
}

function shouldMountProposalCard(
  currentPhase: string | null,
  inFlight: 'idle' | 'generating' | 'modifying' | 'deciding',
): boolean {
  if (currentPhase === 'propuesta') return true
  if (inFlight !== 'idle') return true
  return false
}

export function ChatWindow({
  projectId,
  phase = null,
  phaseReady = false,
  onProjectUpdated,
  onAdvance,
}: ChatWindowProps) {
  const { messages, isStreaming, error, loadingHistory } = chatStore()
  const storePhase = projectsStore((s) => s.currentProject?.current_phase ?? null)
  const currentPhase = phase ?? storePhase
  const proposalInFlight = proposalsStore((s) => s.inFlight)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const [loadingElicitation, setLoadingElicitation] = useState(false)
  const [decisionError, setDecisionError] = useState('')
  const [decisionMessage, setDecisionMessage] = useState('')
  const [showModify, setShowModify] = useState(false)
  const [feedback, setFeedback] = useState('')
  const [awaitingDecision, setAwaitingDecision] = useState(false)
  const [done, setDone] = useState(false)
  const [summary, setSummary] = useState<Record<string, unknown> | null>(null)
  // Aprobación recién hecha en esta pantalla: evita que los botones de decisión
  // "reaparezcan" durante el instante que tarda en recargarse phase_ready.
  const [approvedLocal, setApprovedLocal] = useState(false)
  const [advancing, setAdvancing] = useState(false)
  const [advanceError, setAdvanceError] = useState('')
  const isElicitation = currentPhase === 'requerimientos'
  const proposalLifecycle = proposalsStore((s) => s.currentProposal?.lifecycle)
  const upcomingPhase = nextPhase(currentPhase)

  const renderElicitationState = useCallback((state: ElicitationState) => {
    const restored = state.history.flatMap((item, index) => [
      { id: `elicitation-question-${index}`, role: 'assistant' as const, content: item.pregunta },
      { id: `elicitation-answer-${index}`, role: 'user' as const, content: item.respuesta },
    ])
    if (!state.resumen && state.question) {
      restored.push({ id: 'elicitation-question-current', role: 'assistant' as const, content: state.question })
    }
    chatStore.setState({ messages: restored, error: null })
    setSummary(state.resumen)
    setDone(state.done)
    setDecisionMessage('')
    setDecisionError('')
  }, [])

  const loadElicitation = useCallback(async () => {
    setLoadingElicitation(true)
    try {
      let state = await getElicitationState(projectId)
      if (!state.done && !state.question) state = await sendElicitationMessage(projectId)
      renderElicitationState(state)
    } catch (err) {
      // Antes, si esta llamada fallaba (429 del proveedor, JSON inválido...),
      // quedaba el resumen viejo, sin botones y con el mensaje del backend
      // colgado. Ahora se limpia y se ofrece "Reintentar" (ver más abajo).
      setDecisionMessage('')
      chatStore.setState({ error: err instanceof Error ? err.message : 'Error al cargar la elicitación' })
    } finally {
      setLoadingElicitation(false)
    }
  }, [projectId, renderElicitationState])

  useEffect(() => {
    setDone(false)
    setSummary(null)
    setApprovedLocal(false)
    setAdvanceError('')
    setDecisionMessage('')
    setDecisionError('')
    setShowModify(false)
    if (!isElicitation) return

    chatStore.setState({ messages: [], error: null })
    void loadElicitation()
    return () => {
      chatStore.setState({ messages: [], error: null })
    }
  }, [isElicitation, loadElicitation, projectId])

  useEffect(() => {
    if (isElicitation) return
    const state = chatStore.getState()
    if (state.isStreaming || state.loadingHistory) return
    void state.loadHistory(projectId)
  }, [isElicitation, projectId])

  // La tarjeta de propuesta vive en un store global: si cambia el proyecto se
  // limpia para no mostrar la propuesta de otro.
  const prevProjectId = useRef(projectId)
  useEffect(() => {
    if (prevProjectId.current !== projectId) {
      proposalsStore.getState().reset()
      prevProjectId.current = projectId
    }
  }, [projectId])

  // Al entrar (o volver a entrar) a la fase de propuesta, recuperar la que ya
  // exista en el backend en vez de mostrar "Aún no hay propuesta".
  useEffect(() => {
    if (currentPhase === 'propuesta') void proposalsStore.getState().loadLatest(projectId)
  }, [currentPhase, projectId])

  // Aprobar/rechazar la propuesta cambia phase_ready (y, al rechazar, la fase)
  // en el backend: pedirle al padre que recargue el proyecto.
  const prevLifecycle = useRef(proposalLifecycle)
  useEffect(() => {
    if (
      prevLifecycle.current !== proposalLifecycle &&
      (proposalLifecycle === 'approved' || proposalLifecycle === 'rejected')
    ) {
      void onProjectUpdated?.()
    }
    prevLifecycle.current = proposalLifecycle
  }, [proposalLifecycle, onProjectUpdated])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, isStreaming, loadingElicitation, phaseReady, approvedLocal])

  const handleSend = async (text: string, displayText?: string) => {
    if (!isElicitation) {
      await chatStore.getState().sendMessage(projectId, text, displayText)
      return
    }
    setLoadingElicitation(true)
    chatStore.setState({ isStreaming: true, error: null })
    try {
      renderElicitationState(await sendElicitationMessage(projectId, text))
    } catch (err) {
      chatStore.setState({ error: err instanceof Error ? err.message : 'No se pudo enviar la respuesta' })
    } finally {
      chatStore.setState({ isStreaming: false })
      setLoadingElicitation(false)
    }
  }

  const handleDecision = async (decision: ElicitationDecision) => {
    if (decision === 'modify' && !feedback.trim()) {
      setDecisionError('Describe el ajuste que necesitas antes de continuar.')
      return
    }
    setAwaitingDecision(true)
    setDecisionError('')
    try {
      await submitElicitationDecision(projectId, decision, feedback.trim() || undefined)
      setFeedback('')
      setShowModify(false)
      if (decision === 'approve') {
        setApprovedLocal(true)
        setDecisionMessage('')
        await onProjectUpdated?.()
      } else {
        // El resumen anterior ya no es válido: se limpia YA (antes quedaba el
        // resumen viejo en pantalla, sin botones, mientras el modelo
        // regeneraba) y se muestra un mensaje propio en vez del texto crudo del
        // backend ("Llama a /elicitation/message para continuar").
        setApprovedLocal(false)
        setSummary(null)
        setDone(false)
        setDecisionMessage(
          decision === 'modify'
            ? 'Ajuste registrado. Actualizando el resumen de requerimientos...'
            : 'Requerimientos reiniciados. Preparando la elicitación de nuevo...',
        )
        await onProjectUpdated?.()
        await loadElicitation()
      }
    } catch (err) {
      setDecisionError(err instanceof Error ? err.message : 'No se pudo registrar la decisión')
    } finally {
      setAwaitingDecision(false)
    }
  }

  const handleAdvance = async () => {
    if (!onAdvance) return
    setAdvancing(true)
    setAdvanceError('')
    try {
      await onAdvance()
    } catch (err) {
      setAdvanceError(err instanceof Error ? err.message : 'No se pudo avanzar de fase')
    } finally {
      setAdvancing(false)
    }
  }

  const busy = isStreaming || loadingElicitation || awaitingDecision
  const showProposalCard = shouldMountProposalCard(currentPhase, proposalInFlight)
  // Requerimientos: el resumen existe y ya fue aprobado (phase_ready en el
  // backend, o aprobado hace un instante acá) -> ya no se vuelve a pedir la
  // decisión; se ofrece avanzar. Sin esto, cada vez que se volvía a entrar el
  // resumen pedía aprobar de nuevo porque nada consultaba phase_ready ni
  // llamaba a /advance.
  const requirementsApproved = isElicitation && done && (phaseReady || approvedLocal)
  const needsDecision = isElicitation && done && !requirementsApproved
  const showAdvanceBanner =
    !!upcomingPhase && !!onAdvance && (isElicitation ? requirementsApproved : phaseReady)

  const modifyForm = showModify && (
    <div className="mt-3 space-y-2">
      <label className="block font-medium" htmlFor="elicitation-feedback">¿Qué debe ajustarse?</label>
      <textarea id="elicitation-feedback" value={feedback} onChange={(event) => setFeedback(event.target.value)} rows={3} className="w-full rounded border border-blue-200 p-2 text-gray-900" placeholder="Describe los cambios que necesitas en el resumen..." />
      <button disabled={busy} onClick={() => void handleDecision('modify')} className="rounded bg-blue-600 px-3 py-2 text-white hover:bg-blue-700 disabled:opacity-50">Enviar ajuste</button>
    </div>
  )

  return (
    <div className="flex flex-col h-full">
      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {loadingElicitation && messages.length === 0 && (
          <div className="text-center text-gray-500 py-8">Preparando la elicitación...</div>
        )}
        {messages.length === 0 && !busy && !loadingHistory && !showProposalCard && (
          <div className="text-center text-gray-500 py-8">
            <svg className="mx-auto h-12 w-12 text-gray-300 mb-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
            </svg>
            <p>Envía un mensaje para comenzar la conversación</p>
          </div>
        )}
        {messages.map((message) => (
          <MessageBubble key={message.id} message={message} projectId={projectId} onSendMessage={handleSend} />
        ))}
        {isElicitation && summary && <SummaryView resumen={summary} />}
        {showProposalCard && <ProposalCard forceMount projectId={projectId} />}
        {busy && (
          <div className="flex justify-start">
            <div className="bg-gray-100 px-4 py-2 rounded-lg">
              <div className="flex items-center gap-1">
                <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '0ms' }}></span>
                <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '150ms' }}></span>
                <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '300ms' }}></span>
              </div>
            </div>
          </div>
        )}
        {error && (
          <div className="flex flex-wrap items-center justify-between gap-2 p-3 bg-red-50 text-red-700 rounded-lg text-sm">
            <span>{error}</span>
            {isElicitation && (
              <button type="button" disabled={busy} onClick={() => void loadElicitation()} className="rounded border border-red-300 px-3 py-1 text-red-700 hover:bg-red-100 disabled:opacity-50">
                Reintentar
              </button>
            )}
          </div>
        )}
        {needsDecision && (
          <div className="rounded-lg border border-blue-200 bg-blue-50 p-4 text-sm text-blue-900">
            <p className="mb-1">¿El resumen representa las necesidades del proyecto?</p>
            <p className="mb-3 text-xs text-blue-700">
              ¿Subiste un documento nuevo (acta, notas)? Usa «Modificar» para que se incorpore al resumen.
            </p>
            <div className="flex flex-wrap gap-2">
              <button disabled={busy} onClick={() => void handleDecision('approve')} className="rounded bg-blue-600 px-3 py-2 text-white hover:bg-blue-700 disabled:opacity-50">Aprobar</button>
              <button disabled={busy} onClick={() => setShowModify(true)} className="rounded border border-blue-600 px-3 py-2 text-blue-700 hover:bg-blue-100 disabled:opacity-50">Modificar</button>
              <button disabled={busy} onClick={() => void handleDecision('reject')} className="rounded border border-red-300 px-3 py-2 text-red-700 hover:bg-red-50 disabled:opacity-50">Rechazar</button>
            </div>
            {modifyForm}
            {decisionError && <p className="mt-2 text-red-700">{decisionError}</p>}
          </div>
        )}
        {showAdvanceBanner && (
          <div className="rounded-lg border border-green-200 bg-green-50 p-4 text-sm text-green-900" data-testid="phase-ready-banner">
            <p className="mb-3">
              {isElicitation ? 'Requerimientos aprobados ✓' : `Fase de ${phaseLabel(currentPhase)} aprobada ✓`}
              {' '}Ya puedes continuar a la fase de <span className="font-semibold">{phaseLabel(upcomingPhase)}</span>.
            </p>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                data-testid="advance-phase"
                disabled={advancing || busy}
                onClick={() => void handleAdvance()}
                className="rounded bg-green-600 px-3 py-2 font-semibold text-white hover:bg-green-700 disabled:opacity-50"
              >
                {advancing ? 'Avanzando...' : `Continuar a ${phaseLabel(upcomingPhase)}`}
              </button>
              {isElicitation && (
                <button disabled={busy || advancing} onClick={() => setShowModify(true)} className="rounded border border-green-600 px-3 py-2 text-green-800 hover:bg-green-100 disabled:opacity-50">Pedir un ajuste</button>
              )}
            </div>
            {isElicitation && modifyForm}
            {(advanceError || decisionError) && <p className="mt-2 text-red-700">{advanceError || decisionError}</p>}
          </div>
        )}
        {decisionMessage && <div className="rounded-lg bg-green-50 p-3 text-sm text-green-800">{decisionMessage}</div>}
        <div ref={messagesEndRef} />
      </div>
      <ChatInput
        projectId={projectId}
        onSend={handleSend}
        disabled={busy || loadingHistory || (isElicitation && done)}
        attachDisabled={busy || loadingHistory}
      />
    </div>
  )
}
