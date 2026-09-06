import { useEffect, useRef } from 'react'
import { chatStore } from '../stores/chatStore'
import { ChatInput } from './ChatInput'
import { MessageBubble } from './MessageBubble'

interface ChatWindowProps {
  projectId: number
}

export function ChatWindow({ projectId }: ChatWindowProps) {
  const { messages, isStreaming, error, loadingHistory } = chatStore()
  const messagesEndRef = useRef<HTMLDivElement>(null)

  // Scroll to bottom on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, isStreaming])

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
    await chatStore.getState().sendMessage(projectId, text)
  }

  return (
    <div className="flex flex-col h-full">
      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {messages.length === 0 && !isStreaming && !loadingHistory && (
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

        <div ref={messagesEndRef} />
      </div>

      <ChatInput projectId={projectId} onSend={handleSend} disabled={isStreaming} />
    </div>
  )
}
