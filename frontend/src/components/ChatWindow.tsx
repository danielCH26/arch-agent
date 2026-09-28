import { useEffect, useRef } from 'react'
import { chatStore } from '../stores/chatStore'
import { ChatInput } from './ChatInput'
import { MessageBubble } from './MessageBubble'
import { ProposalCard } from './ProposalCard'
import robotAvatar from '../assets/robot-avatar.png'

interface ChatWindowProps {
  projectId: number
  phase?: string | null
  onProposalPhaseChanged?: () => void | Promise<void>
}

export function ChatWindow({ projectId, phase, onProposalPhaseChanged }: ChatWindowProps) {
  const { messages, isStreaming, error, loadingHistory } = chatStore()
  const messagesEndRef = useRef<HTMLDivElement>(null)

  // Cada proyecto tiene una conversación propia en el backend. El guard evita
  // el doble GET que React StrictMode puede disparar durante el montaje.
  useEffect(() => {
    const state = chatStore.getState()
    if (
      (state.loadingHistory || state.isStreaming) &&
      state.activeProjectId === projectId
    ) {
      return
    }
    void state.loadHistory(projectId)
  }, [projectId])

  // Scroll to bottom on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, isStreaming])

  const handleSend = async (text: string) => {
    await chatStore.getState().sendMessage(projectId, text)
  }

  return (
    <div className="flex flex-col h-full">
      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {phase === 'propuesta' && (
          <ProposalCard projectId={projectId} onPhaseChanged={onProposalPhaseChanged} />
        )}
        {loadingHistory && messages.length === 0 && (
          <div className="flex justify-center py-8" aria-label="Cargando historial del chat">
            <div className="h-6 w-6 animate-spin rounded-full border-2 border-sky-200 border-b-sky-600" />
          </div>
        )}

        {messages.length === 0 && !isStreaming && !loadingHistory && (
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

        {isStreaming && (
          <div className="flex items-start gap-2 justify-start">
            <img src={robotAvatar} alt="" aria-hidden="true" draggable={false} className="mt-1 h-9 w-auto shrink-0 select-none" />
            <div className="rounded-2xl rounded-tl-sm border border-sky-200 bg-sky-50 px-4 py-2 shadow-sm">
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

        <div ref={messagesEndRef} />
      </div>

      <ChatInput projectId={projectId} onSend={handleSend} disabled={isStreaming || loadingHistory} />
    </div>
  )
}
