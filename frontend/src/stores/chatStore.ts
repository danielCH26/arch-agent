import { create } from 'zustand'
import { createChatStream } from '../api/chat'

export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
}

interface ChatState {
  messages: Message[]
  isStreaming: boolean
  error: string | null

  sendMessage: (projectId: number | null, text: string) => Promise<void>
  addUserMessage: (content: string) => void
  addAssistantMessage: (content: string) => void
  appendToLastAssistantMessage: (content: string) => void
  clearMessages: () => void
  setError: (error: string | null) => void
}

export const chatStore = create<ChatState>((set) => ({
  messages: [],
  isStreaming: false,
  error: null,

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
}))
