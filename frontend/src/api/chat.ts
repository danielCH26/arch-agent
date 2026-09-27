import { authStore } from '../stores/authStore'
import { apiFetch } from './client'
import type { DiagramDecision } from './diagrams'

export interface ChatRequest {
  project_id: number | null
  message: string
  display_message?: string
}

export interface RagSource {
  source_type: string | null
  name: string | null
  similarity: number | null
}

export interface Attachment {
  id?: string
  kind: 'screenshot'
  mime: 'image/png'
  url: string
  filename: string
  decision?: DiagramDecision | null
}

export interface ChatHistoryMessage {
  id: number
  role: 'user' | 'assistant' | 'system'
  content: string
  citations: RagSource[]
  attachments?: Attachment[]
  created_at: string | null
}

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
  onToken: (token: string) => void
  onDone: () => void
  onError: (error: string) => void
  onSources?: (sources: RagSource[]) => void
  onAttachment?: (attachment: Attachment) => void
  onDiagramIssue?: (message: string) => void
}

function dispatchSSEEvent(rawEvent: string, callbacks: StreamCallbacks): boolean {
  let eventName = 'message'
  const dataLines: string[] = []

  for (const line of rawEvent.split('\n')) {
    if (line.startsWith('event:')) {
      eventName = line.slice(6).trim()
    } else if (line.startsWith('data:')) {
      dataLines.push(line.slice(5).trim())
    }
  }

  const rawData = dataLines.join('\n')

  if (eventName === 'sources' && rawData) {
    try {
      callbacks.onSources?.(JSON.parse(rawData) as RagSource[])
    } catch {
      callbacks.onSources?.([])
    }
    return false
  }

  if (eventName === 'token' && rawData) {
    try {
      const data = JSON.parse(rawData)
      callbacks.onToken(data.delta || data)
    } catch {
      callbacks.onToken(rawData)
    }
    return false
  }

  if (eventName === 'attachment' && rawData && callbacks.onAttachment) {
    try {
      callbacks.onAttachment(JSON.parse(rawData) as Attachment)
    } catch {
      // Ignore malformed optional attachment payloads.
    }
    return false
  }

  if (eventName === 'diagram_validated' && rawData && callbacks.onDiagramIssue) {
    try {
      const data = JSON.parse(rawData) as { valid?: boolean; error?: string | null }
      if (data.valid === false) {
        callbacks.onDiagramIssue(
          `No pude generar el diagrama: ${data.error || 'sintaxis Mermaid inválida'}.`,
        )
      }
    } catch {
      // Ignore unexpected optional payloads.
    }
    return false
  }

  if (eventName === 'degraded' && rawData) {
    try {
      const data = JSON.parse(rawData) as {
        message?: string
        source?: string
        reason?: string
        nodes?: string[]
      }
      const isGroundingWarning = data.reason === 'diagram_grounding_warning'
      if ((data.source === 'puppeteer' || isGroundingWarning) && callbacks.onDiagramIssue) {
        let text = data.message || 'No se pudo renderizar el diagrama a imagen.'
        if (isGroundingWarning && data.nodes && data.nodes.length > 0) {
          text += ` Nodos: ${data.nodes.join(', ')}.`
        }
        callbacks.onDiagramIssue(text)
      } else {
        console.warn('[chat] degraded event (no-op para el usuario):', data)
      }
    } catch {
      // Ignore unexpected optional payloads.
    }
    return false
  }

  if (eventName === 'done') {
    callbacks.onDone()
    return true
  }

  if (eventName === 'error' && rawData) {
    try {
      callbacks.onError(JSON.parse(rawData))
    } catch {
      callbacks.onError(rawData)
    }
    return true
  }

  return false
}

export function createChatStream(
  message: string,
  projectId: number | null,
  callbacks: StreamCallbacks,
  displayMessage?: string,
): () => void {
  const { onToken, onDone, onError, onSources, onAttachment, onDiagramIssue } = callbacks
  const token = authStore.getState().token

  const controller = new AbortController()
  const signal = controller.signal

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
          ...(displayMessage ? { display_message: displayMessage } : {}),
        } as ChatRequest),
        signal,
      })

      if (!response.ok) {
        const data = await response.json().catch(() => ({}))
        onError((data.detail as string) || 'Chat request failed')
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
        const events = buffer.split(/\r?\n\r?\n/)
        buffer = events.pop() || ''

        for (const event of events) {
          if (!event.trim()) continue
          const shouldStop = dispatchSSEEvent(event, {
            onToken,
            onDone,
            onError,
            onSources,
            onAttachment,
            onDiagramIssue,
          })
          if (shouldStop) return
        }
      }

      if (buffer.trim()) {
        const shouldStop = dispatchSSEEvent(buffer, {
          onToken,
          onDone,
          onError,
          onSources,
          onAttachment,
          onDiagramIssue,
        })
        if (shouldStop) return
      }

      onDone()
    } catch (err) {
      if (err instanceof Error && err.name === 'AbortError') return
      onError(err instanceof Error ? err.message : 'Unknown error')
    }
  })()

  return () => {
    controller.abort()
  }
}

export async function fetchChatHistory(
  projectId: number,
  limit: number = 5,
): Promise<ChatHistoryMessage[]> {
  const token = authStore.getState().token
  const clampedLimit = Math.max(1, Math.min(50, Math.floor(limit)))

  const response = await fetch(
    `/api/chat/history?project_id=${encodeURIComponent(String(projectId))}&limit=${clampedLimit}`,
    {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    },
  )

  if (!response.ok) return []

  const payload = (await response.json()) as { messages?: ChatHistoryMessage[] }
  if (!Array.isArray(payload.messages)) return []

  return payload.messages.map((row) => ({
    ...row,
    attachments: _normaliseHistoryAttachments(row.attachments),
  }))
}

export function _normaliseHistoryAttachments(raw: unknown): Attachment[] {
  if (!Array.isArray(raw)) return []
  return raw.filter(
    (item): item is Attachment =>
      typeof item === 'object' &&
      item !== null &&
      (item as Attachment).kind === 'screenshot' &&
      typeof (item as Attachment).url === 'string',
  )
}
