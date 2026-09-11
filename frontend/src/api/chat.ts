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

// F05: contrato de la elicitación guiada. Estos endpoints viven bajo el
// proyecto, no bajo /api/chat: el backend conserva el historial, genera el
// resumen y registra decisiones en la tabla approvals.
export interface ElicitationState {
  done: boolean
  question: string | null
  resumen: Record<string, unknown> | null
  history: Array<{ pregunta: string; respuesta: string }>
}

export type ElicitationDecision = 'approve' | 'modify' | 'reject'

export interface ElicitationDecisionResult {
  decision: ElicitationDecision
  phase_ready: boolean
  message: string
}

export function getElicitationState(projectId: number): Promise<ElicitationState> {
  return apiFetch<ElicitationState>(`/api/projects/${projectId}/elicitation`)
}

export function sendElicitationMessage(
  projectId: number,
  answer?: string,
): Promise<ElicitationState> {
  return apiFetch<ElicitationState>(`/api/projects/${projectId}/elicitation/message`, {
    method: 'POST',
    body: JSON.stringify(answer ? { answer } : {}),
  })
}

export function submitElicitationDecision(
  projectId: number,
  decision: ElicitationDecision,
  feedback?: string,
): Promise<ElicitationDecisionResult> {
  return apiFetch<ElicitationDecisionResult>(`/api/projects/${projectId}/elicitation/decision`, {
    method: 'POST',
    body: JSON.stringify({ decision, feedback }),
  })
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
