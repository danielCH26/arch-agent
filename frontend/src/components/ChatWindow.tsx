import { useCallback, useEffect, useRef, useState } from 'react'
import { getElicitationState, sendElicitationMessage, submitElicitationDecision, type ElicitationDecision, type ElicitationState } from '../api/chat'
import { chatStore } from '../stores/chatStore'
import { projectsStore } from '../stores/projectsStore'
import { proposalsStore } from '../stores/proposalsStore'
import { ChatInput } from './ChatInput'
import { MessageBubble } from './MessageBubble'
import { ProposalCard } from './proposals/ProposalCard'

interface ChatWindowProps { projectId: number; phase?: string | null }

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

/**
 * Mount condition for ProposalCard (REQ-7 / SCN-8):
 *   - `current_phase === "propuesta"`, OR
 *   - a proposal is currently being streamed (inFlight !== 'idle') so the
 *     card stays visible across the boundary between user-initiated
 *     generate and the assistant's streamed response.
 *
 * In any other phase the chat stays a plain message stream.
 */
function shouldMountProposalCard(
  currentPhase: string | null,
  inFlight: 'idle' | 'generating' | 'modifying' | 'deciding',
): boolean {
  if (currentPhase === 'propuesta') return true
  if (inFlight !== 'idle') return true
  return false
}

export function ChatWindow({ projectId, phase = null }: ChatWindowProps) {
  const { messages, isStreaming, error } = chatStore()
  const currentPhase = projectsStore((s) => s.currentProject?.current_phase ?? null)
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
  const isElicitation = phase === 'requerimientos'

  const renderElicitationState = useCallback((state: ElicitationState) => {
    const restored = state.history.flatMap((item, index) => [
      { id: `elicitation-question-${index}`, role: 'assistant' as const, content: item.pregunta },
      { id: `elicitation-answer-${index}`, role: 'user' as const, content: item.respuesta },
    ])
    if (!state.resumen && state.question) restored.push({ id: 'elicitation-question-current', role: 'assistant' as const, content: state.question })
    chatStore.setState({ messages: restored, error: null })
    setSummary(state.resumen)
    setDone(state.done)
    // La confirmación de una decisión previa (aprobar/modificar/rechazar) ya
    // cumplió su propósito una vez que el nuevo estado terminó de cargar:
    // si queda pegada, tapa los botones de decisión del siguiente resumen
    // (o el input, si la elicitación reinició desde cero).
    setDecisionMessage(''); setDecisionError('')
  }, [])

  const loadElicitation = useCallback(async () => {
    setLoadingElicitation(true)
    try {
      let state = await getElicitationState(projectId)
      // Una sesión nueva se inicia sin enviar una respuesta: el backend retorna FIRST_QUESTION.
      if (!state.done && !state.question) state = await sendElicitationMessage(projectId)
      renderElicitationState(state)
    } catch (err) {
      chatStore.setState({ error: err instanceof Error ? err.message : 'Error al cargar la elicitación' })
    } finally { setLoadingElicitation(false) }
  }, [projectId, renderElicitationState])

  useEffect(() => {
    setDone(false); setSummary(null); setDecisionMessage(''); setDecisionError(''); setShowModify(false)
    if (!isElicitation) return
    // Solo en la fase de elicitación el historial del chat lo dicta el backend;
    // en las demás fases se respeta lo que ya haya en chatStore.
    chatStore.setState({ messages: [], error: null })
    void loadElicitation()
    return () => { chatStore.setState({ messages: [], error: null }) }
  }, [isElicitation, loadElicitation, projectId])

  useEffect(() => { messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages, isStreaming, loadingElicitation])

  // F12 (REQ-9 / SCN-2): on mount, pull the last-N turns from the backend
  // so a page reload restores the conversation. We guard with
  // ``isStreaming === false && loadingHistory === false`` so React
  // StrictMode's intentional double-mount does not double-fire the fetch
  // AND so an in-flight stream is never clobbered by a stale history
  // payload. ``projectId`` is intentionally in the dep array: switching
  // projects re-loads.
  useEffect(() => {
    const state = chatStore.getState()
    if (state.isStreaming || state.loadingHistory) {
      return
    }
    void state.loadHistory(projectId)
    // We deliberately read state via getState() inside the effect so the
    // effect itself can run with empty deps (mount-only).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId])

  const handleSend = async (text: string) => {
    if (!isElicitation) { await chatStore.getState().sendMessage(projectId, text); return }
    setLoadingElicitation(true); chatStore.setState({ isStreaming: true, error: null })
    try { renderElicitationState(await sendElicitationMessage(projectId, text)) }
    catch (err) { chatStore.setState({ error: err instanceof Error ? err.message : 'No se pudo enviar la respuesta' }) }
    finally { chatStore.setState({ isStreaming: false }); setLoadingElicitation(false) }
  }

  const handleDecision = async (decision: ElicitationDecision) => {
    if (decision === 'modify' && !feedback.trim()) { setDecisionError('Describe el ajuste que necesitas antes de continuar.'); return }
    setAwaitingDecision(true); setDecisionError('')
    try {
      const result = await submitElicitationDecision(projectId, decision, feedback.trim() || undefined)
      setDecisionMessage(result.message); setFeedback(''); setShowModify(false)
      if (decision !== 'approve') await loadElicitation()
    } catch (err) { setDecisionError(err instanceof Error ? err.message : 'No se pudo registrar la decisión') }
    finally { setAwaitingDecision(false) }
  }

  const busy = isStreaming || loadingElicitation || awaitingDecision
  const showProposalCard = shouldMountProposalCard(currentPhase, proposalInFlight)
  return (
    <div className="flex flex-col h-full">
      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {loadingElicitation && messages.length === 0 && <div className="text-center text-gray-500 py-8">Preparando la elicitación…</div>}
        {messages.length === 0 && !busy && !showProposalCard && (
          <div className="text-center text-gray-500 py-8">
            <svg className="mx-auto h-12 w-12 text-gray-300 mb-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
            </svg>
            <p>Envía un mensaje para comenzar la conversación</p>
          </div>
        )}
        {messages.map((message) => <MessageBubble key={message.id} message={message} />)}
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
        {error && <div className="p-3 bg-red-50 text-red-700 rounded-lg text-sm">{error}</div>}
        {isElicitation && done && !decisionMessage && <div className="rounded-lg border border-blue-200 bg-blue-50 p-4 text-sm text-blue-900">
          <p className="mb-3">¿El resumen representa las necesidades del proyecto?</p>
          <div className="flex flex-wrap gap-2">
            <button disabled={busy} onClick={() => void handleDecision('approve')} className="rounded bg-blue-600 px-3 py-2 text-white hover:bg-blue-700 disabled:opacity-50">Aprobar</button>
            <button disabled={busy} onClick={() => setShowModify(true)} className="rounded border border-blue-600 px-3 py-2 text-blue-700 hover:bg-blue-100 disabled:opacity-50">Modificar</button>
            <button disabled={busy} onClick={() => void handleDecision('reject')} className="rounded border border-red-300 px-3 py-2 text-red-700 hover:bg-red-50 disabled:opacity-50">Rechazar</button>
          </div>
          {showModify && <div className="mt-3 space-y-2">
            <label className="block font-medium" htmlFor="elicitation-feedback">¿Qué debe ajustarse?</label>
            <textarea id="elicitation-feedback" value={feedback} onChange={(event) => setFeedback(event.target.value)} rows={3} className="w-full rounded border border-blue-200 p-2 text-gray-900" placeholder="Describe los cambios que necesitas en el resumen..." />
            <button disabled={busy} onClick={() => void handleDecision('modify')} className="rounded bg-blue-600 px-3 py-2 text-white hover:bg-blue-700 disabled:opacity-50">Enviar ajuste</button>
          </div>}
          {decisionError && <p className="mt-2 text-red-700">{decisionError}</p>}
        </div>}
        {decisionMessage && <div className="rounded-lg bg-green-50 p-3 text-sm text-green-800">{decisionMessage}</div>}
        <div ref={messagesEndRef} />
      </div>
      <ChatInput projectId={projectId} onSend={handleSend} disabled={busy || (isElicitation && done)} />
    </div>
  )
}