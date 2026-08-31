import { authStore } from '../stores/authStore'

export interface ChatRequest {
  project_id: number | null
  message: string
}

export interface Message {
  id: number
  role: 'user' | 'assistant'
  content: string
  created_at: string
  latency_ms?: number
  model?: string
}

interface StreamCallbacks {
  onToken: (token: string) => void
  onDone: () => void
  onError: (error: string) => void
}

function parseSSELine(line: string): { event?: string; data?: string } {
  if (line.startsWith('event:')) {
    return { event: line.slice(6).trim() }
  }
  if (line.startsWith('data:')) {
    return { data: line.slice(5).trim() }
  }
  return {}
}

export function createChatStream(
  message: string,
  projectId: number | null,
  callbacks: StreamCallbacks
): () => void {
  const { onToken, onDone, onError } = callbacks
  const token = authStore.getState().token

  const controller = new AbortController()
  const signal = controller.signal

  // Start the stream immediately
  ;(async () => {
    try {
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          project_id: projectId,
          message,
        } as ChatRequest),
        signal,
      })

      if (!response.ok) {
        const data = await response.json().catch(() => ({}))
        const errorMessage = (data.detail as string) || 'Chat request failed'
        onError(errorMessage)
        return
      }

      if (!response.body) {
        onError('No response body')
        return
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })

        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (!line.trim()) continue

          const parsed = parseSSELine(line)
          if (parsed.event === 'token' && parsed.data) {
            try {
              const data = JSON.parse(parsed.data)
              onToken(data.delta || data)
            } catch {
              onToken(parsed.data)
            }
          } else if (parsed.event === 'done') {
            onDone()
            return
          } else if (parsed.event === 'error' && parsed.data) {
            try {
              const data = JSON.parse(parsed.data)
              onError(data)
            } catch {
              onError(parsed.data)
            }
            return
          }
        }
      }

      // Stream ended without explicit done event
      onDone()
    } catch (err) {
      if (err instanceof Error && err.name === 'AbortError') {
        // Request was cancelled, no need to report error
        return
      }
      onError(err instanceof Error ? err.message : 'Unknown error')
    }
  })()

  // Return cleanup function
  return () => {
    controller.abort()
  }
}

// --- Chat History API ---

export async function getMessages(projectId: number): Promise<Message[]> {
  const token = authStore.getState().token

  const response = await fetch(`/api/chat/messages?project_id=${projectId}`, {
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
  })

  if (!response.ok) {
    const data = await response.json().catch(() => ({}))
    const errorMessage = (data.detail as string) || 'Failed to fetch messages'
    throw new Error(errorMessage)
  }

  return response.json()
}
