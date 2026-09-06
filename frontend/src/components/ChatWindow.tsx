import { useCallback, useEffect, useRef, useState } from 'react'
import { chatStore } from '../stores/chatStore'
import { approveElicitation, getElicitationStatus } from '../api/chat'
import { ChatInput } from './ChatInput'
import { MessageBubble } from './MessageBubble'

interface ChatWindowProps {
  projectId: number
}

export function ChatWindow({ projectId }: ChatWindowProps) {
  const { messages, isStreaming, error } = chatStore()
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const [completed, setCompleted] = useState(false)
  const [approved, setApproved] = useState(false)
  const [loadingConversation, setLoadingConversation] = useState(true)
  const [approvalError, setApprovalError] = useState('')

  const loadConversation = useCallback(async () => {
    setLoadingConversation(true)
    chatStore.setState({ messages: [], error: null })
    try {
      const status = await getElicitationStatus(projectId)
      const restored = status.history.flatMap((item, index) => [
        { id: `question-${index}`, role: 'assistant' as const, content: item.pregunta },
        { id: `answer-${index}`, role: 'user' as const, content: item.respuesta },
      ])
      if (status.summary) {
        const summary = status.summary
        const list = (value: unknown) => Array.isArray(value) && value.length
          ? value.map((item) => `- ${String(item)}`).join('\n') : '- No especificado'
        restored.push({
          id: 'summary', role: 'assistant' as const,
          content: `Resumen de requerimientos para validar\n\nProblema\n${String(summary.problema || 'No especificado')}\n\nUsuarios\n${String(summary.usuarios || 'No especificado')}\n\nFuncionalidades\n${list(summary.funcionalidades)}\n\nRestricciones\n${list(summary.restricciones)}\n\nCalidad\n${list(summary.calidad)}`,
        })
      } else if (status.current_question) {
        restored.push({ id: 'current-question', role: 'assistant' as const, content: status.current_question })
      }
      chatStore.setState({ messages: restored, error: null })
      setCompleted(status.completed)
      setApproved(status.approved)
    } catch (err) {
      chatStore.setState({ error: err instanceof Error ? err.message : 'Error al cargar la elicitación' })
    } finally {
      setLoadingConversation(false)
    }
  }, [projectId])

  useEffect(() => {
    void loadConversation()
  }, [loadConversation])

  // Scroll to bottom on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, isStreaming])

  const handleSend = async (text: string) => {
    await chatStore.getState().sendMessage(projectId, text, () => { void loadConversation() })
  }

  const handleApprove = async () => {
    setApprovalError('')
    try {
      await approveElicitation(projectId)
      setApproved(true)
    } catch (err) {
      setApprovalError(err instanceof Error ? err.message : 'No se pudo aprobar el resumen')
    }
  }

  return (
    <div className="flex flex-col h-full">
      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {loadingConversation && (
          <div className="text-center text-gray-500 py-8">Cargando la elicitación…</div>
        )}

        {messages.length === 0 && !isStreaming && !loadingConversation && (
          <div className="text-center text-gray-500 py-8">
            <svg className="mx-auto h-12 w-12 text-gray-300 mb-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
            </svg>
            <p>Envía un mensaje para comenzar la conversación</p>
          </div>
        )}

        {messages.map((message) => (
          <MessageBubble key={message.id} message={message} />
        ))}

        {isStreaming && (
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
          <div className="p-3 bg-red-50 text-red-700 rounded-lg text-sm">
            {error}
          </div>
        )}

        {completed && !approved && (
          <div className="rounded-lg border border-blue-200 bg-blue-50 p-4 text-sm text-blue-900">
            <p className="mb-3">¿El resumen representa las necesidades del proyecto?</p>
            <button onClick={handleApprove} className="rounded bg-blue-600 px-3 py-2 text-white hover:bg-blue-700">
              Aprobar requerimientos
            </button>
            {approvalError && <p className="mt-2 text-red-700">{approvalError}</p>}
          </div>
        )}

        {approved && (
          <div className="rounded-lg bg-green-50 p-3 text-sm text-green-800">
            Requerimientos aprobados. La fase está lista para avanzar.
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      <ChatInput projectId={projectId} onSend={handleSend} disabled={isStreaming || completed || loadingConversation} />
    </div>
  )
}
