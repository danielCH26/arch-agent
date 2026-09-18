import { create } from 'zustand'
import {
  createChatStream,
  fetchChatHistory,
  type Attachment,
  type ChatHistoryMessage,
  type RagSource,
} from '../api/chat'

export interface Message {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  // Fuentes RAG (PGVector) usadas para generar esta respuesta. undefined
  // mientras no ha llegado el evento 'sources'; [] si llego pero no hubo
  // match relevante.
  sources?: RagSource[]
  // F13 (REQ-PMCP-1 / REQ-ATT-3): uno o mas attachments inline (PNG de
  // un diagrama Mermaid renderizado). El backend emite ``event: attachment``
  // despues del ultimo token; el callback los apendea aqui para que el
  // componente MessageBubble los renderice bajo el bloque de markdown.
  attachments?: Attachment[]
}

interface ChatState {
  messages: Message[]
  isStreaming: boolean
  error: string | null
  // F12 (REQ-8): true while loadHistory is in flight so the mount-time
  // useEffect can avoid double-firing under React StrictMode.
  loadingHistory: boolean

  sendMessage: (projectId: number | null, text: string) => Promise<void>
  addUserMessage: (content: string) => void
  addSystemMessage: (content: string) => void
  addAssistantMessage: (content: string) => void
  appendToLastAssistantMessage: (content: string) => void
  clearMessages: () => void
  setError: (error: string | null) => void
  // F12 (REQ-8): replaces messages atomically with the backend history.
  loadHistory: (projectId: number, limit?: number) => Promise<void>
}

export const chatStore = create<ChatState>((set) => ({
  messages: [],
  isStreaming: false,
  error: null,
  loadingHistory: false,

  sendMessage: async (projectId: number | null, text: string) => {
    // Add user message
    const userMessage: Message = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: text,
    }
    set((state) => ({
      messages: [...state.messages, userMessage],
      isStreaming: true,
      error: null,
    }))

    // Create placeholder for assistant response
    const assistantMessageId = `assistant-${Date.now()}`
    set((state) => ({
      messages: [
        ...state.messages,
        { id: assistantMessageId, role: 'assistant', content: '' },
      ],
    }))

    // Start streaming
    let fullResponse = ''

    // Start the stream - cleanup is handled internally
    createChatStream(text, projectId, {
      onSources: (sources) => {
        set((state) => ({
          messages: state.messages.map((msg) =>
            msg.id === assistantMessageId ? { ...msg, sources } : msg
          ),
        }))
      },
      onToken: (token: string) => {
        fullResponse += token
        set((state) => ({
          messages: state.messages.map((msg) =>
            msg.id === assistantMessageId
              ? { ...msg, content: fullResponse }
              : msg
          ),
        }))
      },
      // F13: append each `` event: attachment`` payload to the in-flight
    // assistant message's ``attachments`` list. The order in which the
    // events arrive is preserved so the UI can stack the screenshots
    // chronologically under the source code.
    onAttachment: (attachment: Attachment) => {
      set((state) => ({
        messages: state.messages.map((msg) =>
          msg.id === assistantMessageId
            ? {
                ...msg,
                attachments: [...(msg.attachments ?? []), attachment],
              }
            : msg
        ),
      }))
    },
      onDone: () => {
        set({ isStreaming: false })
      },
      onError: (errorMessage: string) => {
        set((state) => ({
          isStreaming: false,
          error: errorMessage,
          messages: state.messages.map((msg) =>
            msg.id === assistantMessageId
              ? { ...msg, content: fullResponse || 'Error: ' + errorMessage }
              : msg
          ),
        }))
      },
    })

    // Store cleanup function for potential cancellation
    // Note: We don't expose cancellation in this implementation
    // but the stream can be aborted by component unmount
  },

  addUserMessage: (content: string) => {
    const message: Message = {
      id: `user-${Date.now()}`,
      role: 'user',
      content,
    }
    set((state) => ({
      messages: [...state.messages, message],
    }))
  },

  addAssistantMessage: (content: string) => {
    const message: Message = {
      id: `assistant-${Date.now()}`,
      role: 'assistant',
      content,
    }
    set((state) => ({
      messages: [...state.messages, message],
    }))
  },

  addSystemMessage: (content: string) => {
    const message: Message = {
      id: `system-${Date.now()}`,
      role: 'system',
      content,
    }
    set((state) => ({
      messages: [...state.messages, message],
    }))
  },

  appendToLastAssistantMessage: (content: string) => {
    set((state) => {
      const messages = [...state.messages]
      const lastIndex = messages.length - 1
      if (lastIndex >= 0 && messages[lastIndex].role === 'assistant') {
        messages[lastIndex] = {
          ...messages[lastIndex],
          content: messages[lastIndex].content + content,
        }
      }
      return { messages }
    })
  },

  clearMessages: () => {
    set({ messages: [], error: null })
  },

  setError: (error: string | null) => {
    set({ error })
  },

  // F12 (REQ-8): fetch history for (user, project) and replace messages
  // atomically. On error: leave messages untouched and clear the flag.
  loadHistory: async (projectId: number, limit: number = 5) => {
    set({ loadingHistory: true })
    try {
      const rows = await fetchChatHistory(projectId, limit)
      // The backend returns rows newest-first; the chat UI shows them in
      // chronological order so the conversation reads top-to-bottom.
      const ordered = [...rows].reverse()
      const messages: Message[] = ordered.map((row: ChatHistoryMessage) => ({
        id: `history-${row.id}`,
        role: row.role,
        content: row.content,
        sources: row.citations,
        attachments: row.attachments,
      }))
      // Atomic replacement: do not interleave with in-flight streaming
      // tokens (REQ-9 guards in ChatWindow ensure this is a no-op while
      // a stream is active).
      set({ messages, loadingHistory: false })
    } catch {
      // Per REQ-8: on error, clear loadingHistory and leave messages untouched.
      set({ loadingHistory: false })
    }
  },
}))