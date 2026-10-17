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
  // true si el historial cargado llegó al límite de la API (50 mensajes):
  // puede haber mensajes anteriores que no se muestran.
  historyTruncated: boolean

  // `displayText`: lo que escribió el usuario cuando `text` es un prompt más
  // largo para el agente. Se muestra en la burbuja y se persiste en el backend.
  // Devuelve false si no se envió (ya hay una respuesta en curso).
  sendMessage: (projectId: number | null, text: string, displayText?: string) => Promise<boolean>
  addUserMessage: (content: string) => void
  addSystemMessage: (content: string) => void
  addAssistantMessage: (content: string) => void
  appendToLastAssistantMessage: (content: string) => void
  clearMessages: () => void
  setError: (error: string | null) => void
  loadHistory: (projectId: number, limit?: number) => Promise<void>
}

let latestHistoryRequest = 0
// Límite de mensajes por consulta de GET /api/chat/history.
export const HISTORY_LIMIT = 50

// Proyectos con una respuesta en curso. Si la persona cambia de proyecto, el
// stream sigue en segundo plano (el backend guarda el turno al terminar): al
// volver a ese proyecto se muestra "escribiendo…" y, cuando termina, se
// recarga el historial.
const runningStreams = new Set<number | null>()

export const chatStore = create<ChatState>((set, get) => ({
  messages: [],
  isStreaming: false,
  error: null,
  loadingHistory: false,
  activeProjectId: null,
  historyTruncated: false,

  sendMessage: async (projectId: number | null, text: string, displayText?: string) => {
    // Una respuesta a la vez: evita dos streams simultáneos (p. ej. al
    // decidir sobre un diagrama mientras el agente aún responde).
    if (get().isStreaming || runningStreams.has(projectId)) return false
    runningStreams.add(projectId)

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

    // Fin del stream: si mientras tanto se recargó el historial de este
    // proyecto (se salió y se volvió), el mensaje provisional ya no está y se
    // vuelve a pedir el historial, que ya incluye la respuesta guardada.
    const finish = () => {
      runningStreams.delete(projectId)
      if (get().activeProjectId !== projectId) return false
      if (!get().messages.some((msg) => msg.id === assistantMessageId)) {
        set({ isStreaming: false })
        if (projectId !== null) void get().loadHistory(projectId)
        return false
      }
      return true
    }

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
        if (!finish()) return
        set({ isStreaming: false })
      },
      onError: (errorMessage: string) => {
        if (!finish()) return
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

    return true
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

  loadHistory: async (projectId: number, limit: number = HISTORY_LIMIT) => {
    const requestId = ++latestHistoryRequest

    // Nunca mostramos la conversación de otro proyecto mientras llega esta
    // respuesta. Esto también produce el estado de carga del diseño actual.
    set({
      messages: [],
      error: null,
      loadingHistory: true,
      // Los callbacks de un stream de otro proyecto se ignoran por
      // activeProjectId. Si este proyecto tiene uno en curso, el input queda
      // bloqueado hasta que termine (ver runningStreams).
      isStreaming: runningStreams.has(projectId),
      activeProjectId: projectId,
      historyTruncated: false,
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
      set({ messages, loadingHistory: false, historyTruncated: rows.length >= HISTORY_LIMIT })
    } catch (err) {
      if (requestId !== latestHistoryRequest) return
      set({
        loadingHistory: false,
        error: err instanceof Error ? err.message : 'No se pudo cargar el historial del chat',
      })
    }
  },
}))
