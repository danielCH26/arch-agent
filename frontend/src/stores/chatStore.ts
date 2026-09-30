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
  attachments?: Attachment[]
  // Avisos del backend (evento `degraded`) sobre el diagrama de esta respuesta.
  notices?: string[]
}

interface ChatState {
  messages: Message[]
  isStreaming: boolean
  error: string | null
  loadingHistory: boolean
  activeProjectId: number | null

  // `displayText`: lo que escribió el usuario cuando `text` es un prompt más
  // largo para el agente. Se muestra en la burbuja y se persiste en el backend.
  sendMessage: (projectId: number | null, text: string, displayText?: string) => Promise<void>
  addUserMessage: (content: string) => void
  addSystemMessage: (content: string) => void
  addAssistantMessage: (content: string) => void
  appendToLastAssistantMessage: (content: string) => void
  clearMessages: () => void
  setError: (error: string | null) => void
  loadHistory: (projectId: number, limit?: number) => Promise<void>
}

let latestHistoryRequest = 0

export const chatStore = create<ChatState>((set, get) => ({
  messages: [],
  isStreaming: false,
  error: null,
  loadingHistory: false,
  activeProjectId: null,

  sendMessage: async (projectId: number | null, text: string, displayText?: string) => {
    // Add user message
    const userMessage: Message = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: displayText || text,
    }
    set((state) => ({
      messages: [...state.messages, userMessage],
      isStreaming: true,
      error: null,
      activeProjectId: projectId,
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
        if (get().activeProjectId !== projectId) return
        set((state) => ({
          messages: state.messages.map((msg) =>
            msg.id === assistantMessageId ? { ...msg, sources } : msg
          ),
        }))
      },
      onToken: (token: string) => {
        if (get().activeProjectId !== projectId) return
        fullResponse += token
        set((state) => ({
          messages: state.messages.map((msg) =>
            msg.id === assistantMessageId
              ? { ...msg, content: fullResponse }
              : msg
          ),
        }))
      },
      onAttachment: (attachment) => {
        if (get().activeProjectId !== projectId) return
        set((state) => ({
          messages: state.messages.map((msg) =>
            msg.id === assistantMessageId
              ? { ...msg, attachments: [...(msg.attachments ?? []), attachment] }
              : msg
          ),
        }))
      },
      onNotice: (notice) => {
        if (get().activeProjectId !== projectId) return
        set((state) => ({
          messages: state.messages.map((msg) =>
            msg.id === assistantMessageId
              ? { ...msg, notices: [...(msg.notices ?? []), notice] }
              : msg
          ),
        }))
      },
      onDone: () => {
        if (get().activeProjectId !== projectId) return
        set({ isStreaming: false })
      },
      onError: (errorMessage: string) => {
        if (get().activeProjectId !== projectId) return
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
    }, displayText)

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
    set({ messages: [], error: null, activeProjectId: null })
  },

  setError: (error: string | null) => {
    set({ error })
  },

  loadHistory: async (projectId: number, limit: number = 50) => {
    const requestId = ++latestHistoryRequest

    // Nunca mostramos la conversación de otro proyecto mientras llega esta
    // respuesta. Esto también produce el estado de carga del diseño actual.
    set({
      messages: [],
      error: null,
      loadingHistory: true,
      // Si la persona cambia de proyecto durante un stream, los callbacks del
      // stream anterior se ignoran por activeProjectId. Liberamos el input
      // para que el proyecto recién abierto no quede bloqueado.
      isStreaming: false,
      activeProjectId: projectId,
    })

    try {
      const rows = await fetchChatHistory(projectId, limit)
      if (requestId !== latestHistoryRequest) return

      // La API entrega los más recientes primero; el chat se lee de arriba
      // hacia abajo en orden cronológico.
      const messages: Message[] = [...rows].reverse().map((row: ChatHistoryMessage) => ({
        id: `history-${row.id}`,
        role: row.role,
        content: row.content,
        sources: row.citations,
        attachments: row.attachments,
      }))
      set({ messages, loadingHistory: false })
    } catch (err) {
      if (requestId !== latestHistoryRequest) return
      set({
        loadingHistory: false,
        error: err instanceof Error ? err.message : 'No se pudo cargar el historial del chat',
      })
    }
  },
}))
