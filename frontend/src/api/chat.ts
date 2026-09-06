import { authStore } from '../stores/authStore'

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

// F12 (REQ-7 / REQ-8): una fila persistida por el backend, devuelta por
// GET /api/chat/history. Coincide con la forma del payload que arma
// app/api/chat.py::chat_history.
export interface ChatHistoryMessage {
  id: number
  role: 'user' | 'assistant' | 'system'
  content: string
  citations: RagSource[]
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
  const { onToken, onDone, onError, onSources } = callbacks
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
          const shouldStop = dispatchSSEEvent(event, { onToken, onDone, onError, onSources })
          if (shouldStop) return
        }
      }

      if (buffer.trim()) {
        const shouldStop = dispatchSSEEvent(buffer, { onToken, onDone, onError, onSources })
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

// -----------------------------------------------------------------------------
// F12 (REQ-7, REQ-8): history endpoint client
// -----------------------------------------------------------------------------

/**
 * GET /api/chat/history?project_id=<int>&limit=<int>
 *
 * Returns the last ``limit`` messages (default 5, max 50) for the
 * authenticated user + project, ordered newest-first. The backend is
 * expected to return 200 with `{messages: []}` when Postgres is down
 * (REQ-11 / SCN-5), so any non-ok response is normalised into an empty
 * array rather than throwing — keeps the frontend mount resilient.
 */
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

  if (!response.ok) {
    // Treat 4xx/5xx as "no history to render" — the store handles the
    // empty case (REQ-8: error path leaves messages untouched and clears
    // loadingHistory).
    return []
  }

  const payload = (await response.json()) as { messages?: ChatHistoryMessage[] }
  return Array.isArray(payload.messages) ? payload.messages : []
}