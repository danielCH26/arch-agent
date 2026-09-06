import { authStore } from '../stores/authStore'
import { apiFetch } from './client'

export interface ChatRequest {
  project_id: number | null
  message: string
}

export interface RagSource {
  source_type: string | null
  name: string | null
  similarity: number | null
}

export interface ElicitationStatus {
  history: Array<{ pregunta: string; respuesta: string }>
  current_question: string | null
  summary: Record<string, unknown> | null
  completed: boolean
  approved: boolean
}

interface StreamCallbacks {
  onSources: (sources: RagSource[]) => void
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
  const { onSources, onToken, onDone, onError } = callbacks
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
          if (parsed.event === 'sources' && parsed.data) {
            try {
              onSources(JSON.parse(parsed.data) as RagSource[])
            } catch {
              onSources([])
            }
          } else if (parsed.event === 'token' && parsed.data) {
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

export async function getElicitationStatus(projectId: number): Promise<ElicitationStatus> {
  return apiFetch<ElicitationStatus>(`/api/chat/${projectId}/elicitation`)
}

export async function approveElicitation(projectId: number): Promise<{ phase_ready: boolean; message: string }> {
  return apiFetch<{ phase_ready: boolean; message: string }>(`/api/chat/${projectId}/elicitation/approve`, {
    method: 'POST',
  })
}
