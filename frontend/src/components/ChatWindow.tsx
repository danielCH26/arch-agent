import { useCallback, useEffect, useRef, useState } from 'react'
import { getElicitationState, sendElicitationMessage, submitElicitationDecision, type ElicitationDecision, type ElicitationState } from '../api/chat'
import { chatStore } from '../stores/chatStore'
import { ChatInput } from './ChatInput'
import { MessageBubble } from './MessageBubble'

interface ChatWindowProps { projectId: number; phase: string | null }

function formatSummary(summary: Record<string, unknown>): string {
  const list = (value: unknown) => Array.isArray(value) && value.length ? value.map((item) => `- ${String(item)}`).join('\n') : '- No especificado'
  return `Resumen de requerimientos para validar\n\nProblema\n${String(summary.problema || 'No especificado')}\n\nUsuarios\n${String(summary.usuarios || 'No especificado')}\n\nFuncionalidades\n${list(summary.funcionalidades)}\n\nRestricciones\n${list(summary.restricciones)}\n\nCalidad\n${list(summary.calidad)}`
}

export function ChatWindow({ projectId, phase }: ChatWindowProps) {
  const { messages, isStreaming, error } = chatStore()
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const [loadingElicitation, setLoadingElicitation] = useState(false)
  const [decisionError, setDecisionError] = useState('')
  const [decisionMessage, setDecisionMessage] = useState('')
  const [showModify, setShowModify] = useState(false)
  const [feedback, setFeedback] = useState('')
  const [awaitingDecision, setAwaitingDecision] = useState(false)
  const [done, setDone] = useState(false)
  const isElicitation = phase === 'requerimientos'

  const renderElicitationState = useCallback((state: ElicitationState) => {
    const restored = state.history.flatMap((item, index) => [
      { id: `elicitation-question-${index}`, role: 'assistant' as const, content: item.pregunta },
      { id: `elicitation-answer-${index}`, role: 'user' as const, content: item.respuesta },
    ])
    if (state.resumen) restored.push({ id: 'elicitation-summary', role: 'assistant' as const, content: formatSummary(state.resumen) })
    else if (state.question) restored.push({ id: 'elicitation-question-current', role: 'assistant' as const, content: state.question })
    chatStore.setState({ messages: restored, error: null })
    setDone(state.done)
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
    chatStore.setState({ messages: [], error: null })
    setDone(false); setDecisionMessage(''); setDecisionError(''); setShowModify(false)
    if (isElicitation) void loadElicitation()
  }, [isElicitation, loadElicitation, projectId])

  useEffect(() => { messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages, isStreaming, loadingElicitation])

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
  return (
    <div className="flex flex-col h-full">
      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {loadingElicitation && messages.length === 0 && <div className="text-center text-gray-500 py-8">Preparando la elicitación…</div>}
        {messages.length === 0 && !busy && <div className="text-center text-gray-500 py-8"><p>Envía un mensaje para comenzar la conversación</p></div>}
        {messages.map((message) => <MessageBubble key={message.id} message={message} />)}
        {busy && <div className="flex justify-start"><div className="bg-gray-100 px-4 py-2 rounded-lg text-sm text-gray-500">Procesando…</div></div>}
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
