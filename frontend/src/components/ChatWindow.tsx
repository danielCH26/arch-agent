import { useEffect, useRef, useState } from 'react'
import { chatStore } from '../stores/chatStore'
import { ChatInput } from './ChatInput'
import { MessageBubble } from './MessageBubble'
import { ProposalCard } from './ProposalCard'
import { ChatHistorySkeleton } from './Skeleton'
import robotAvatar from '../assets/robot-avatar.png'

// Texto plano para el lector de pantalla: sin bloques de código ni marcas
// de markdown.
function toSpokenText(markdown: string): string {
  return markdown
    .replace(/```mermaid[\s\S]*?```/gi, ' (diagrama) ')
    .replace(/```[\s\S]*?```/g, ' (bloque de código) ')
    .replace(/<[^>]+>/g, ' ')
    .replace(/[#*_`>|]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

interface ChatWindowProps {
  projectId: number
  phase?: string | null
  onProposalPhaseChanged?: () => void | Promise<void>
}

export function ChatWindow({ projectId, phase, onProposalPhaseChanged }: ChatWindowProps) {
  const { messages, isStreaming, error, loadingHistory } = chatStore()
  const messagesEndRef = useRef<HTMLDivElement>(null)
  // Anuncios para lectores de pantalla: la respuesta llega por fragmentos,
  // así que se anuncia una sola vez al terminar en vez de marcar la lista
  // de mensajes como región viva.
  const [announcement, setAnnouncement] = useState('')
  const wasStreaming = useRef(false)

  useEffect(() => {
    if (isStreaming && !wasStreaming.current) {
      setAnnouncement('ArchAgent está escribiendo…')
    } else if (!isStreaming && wasStreaming.current) {
      const last = [...messages].reverse().find((message) => message.role === 'assistant')
      const spoken = last ? toSpokenText(last.content) : ''
      setAnnouncement(spoken ? `ArchAgent respondió: ${spoken}` : '')
    }
    wasStreaming.current = isStreaming
  }, [isStreaming, messages])

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
    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    messagesEndRef.current?.scrollIntoView({ behavior: reduceMotion ? 'auto' : 'smooth' })
  }, [messages, isStreaming])

  const handleSend = async (text: string, displayText?: string) => {
    await chatStore.getState().sendMessage(projectId, text, displayText)
  }

  return (
    <div className="flex flex-col h-full">
      <div className="sr-only" aria-live="polite" aria-atomic="true">
        {announcement}
      </div>
      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {phase === 'propuesta' && (
          <ProposalCard projectId={projectId} onPhaseChanged={onProposalPhaseChanged} />
        )}
        {loadingHistory && messages.length === 0 && <ChatHistorySkeleton />}

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
          <div role="alert" className="p-3 bg-red-50 text-red-700 rounded-lg text-sm">
            {error}
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      <ChatInput projectId={projectId} onSend={handleSend} disabled={isStreaming || loadingHistory} />
    </div>
  )
}
