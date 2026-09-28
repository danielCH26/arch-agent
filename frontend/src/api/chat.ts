import { authStore } from '../stores/authStore'
import { apiFetch } from './client'

export interface ChatRequest {
  project_id: number | null
  message: string
}

// Metadata de un documento/patron recuperado por el pipeline RAG (PGVector).
// Se usa para poder mostrar/loguear si una respuesta realmente se apoyo en
// contenido recuperado, en vez de solo confiar en lo que el LLM "dice".
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
  decision?: 'approve' | 'modify' | 'reject' | null
}

/**
 * Mensaje almacenado por el backend. El endpoint devuelve los mensajes más
 * recientes primero; el store los invierte antes de mostrarlos en el chat.
 */
export interface ChatHistoryMessage {
  id: number
  role: 'user' | 'assistant' | 'system'
  content: string
  citations?: RagSource[]
  attachments?: Attachment[]
  created_at: string | null
}

interface StreamCallbacks {
  onToken: (token: string) => void
  onDone: () => void
  onError: (error: string) => void
  // Se dispara UNA vez, antes de los primeros tokens, con la lista de
  // fuentes recuperadas (puede venir vacia si no hubo match o si el
  // retrieval fallo silenciosamente en el backend).
  onSources?: (sources: RagSource[]) => void
  onAttachment?: (attachment: Attachment) => void
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
      // Si viene mal formado, no bloqueamos el resto del stream por esto.
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

  if (eventName === 'attachment' && rawData) {
    try {
      const attachment = JSON.parse(rawData) as Attachment
      if (attachment.kind === 'screenshot' && typeof attachment.url === 'string') {
        callbacks.onAttachment?.(attachment)
      }
    } catch {
      // Un adjunto malformado no debe interrumpir el stream del chat.
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
  callbacks: StreamCallbacks
): () => void {
  const { onToken, onDone, onError, onSources, onAttachment } = callbacks
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

        const events = buffer.split(/\r?\n\r?\n/)
        buffer = events.pop() || ''

        for (const event of events) {
          if (!event.trim()) continue
          const shouldStop = dispatchSSEEvent(event, { onToken, onDone, onError, onSources, onAttachment })
          if (shouldStop) return
        }
      }

      if (buffer.trim()) {
        const shouldStop = dispatchSSEEvent(buffer, { onToken, onDone, onError, onSources, onAttachment })
        if (shouldStop) return
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

/** Obtiene el historial persistido para un único proyecto autenticado. */
export async function fetchChatHistory(
  projectId: number,
  limit: number = 50,
): Promise<ChatHistoryMessage[]> {
  const clampedLimit = Math.max(1, Math.min(50, Math.floor(limit)))
  const payload = await apiFetch<{ messages?: ChatHistoryMessage[] }>(
    `/api/chat/history?project_id=${encodeURIComponent(String(projectId))}&limit=${clampedLimit}`,
  )

  if (!Array.isArray(payload.messages)) return []

  return payload.messages.map((message) => ({
    ...message,
    attachments: normalizeAttachments(message.attachments),
  }))
}

function normalizeAttachments(value: unknown): Attachment[] {
  if (!Array.isArray(value)) return []
  return value.filter(
    (attachment): attachment is Attachment =>
      typeof attachment === 'object' &&
      attachment !== null &&
      (attachment as Attachment).kind === 'screenshot' &&
      typeof (attachment as Attachment).url === 'string',
  )
}
