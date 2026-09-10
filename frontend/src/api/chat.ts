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

// F13 (REQ-PMCP-1 / REQ-ATT-3): un attachment servido por el backend
// (render Puppeteer → PNG inline). El ``url`` lleva un token firmado
// (TTL 5 min, ver app/core/attachment_tokens.py) — el <img src=...> no
// puede llevar Authorization, por eso va en la query string.
export interface Attachment {
  kind: 'screenshot'
  mime: 'image/png'
  url: string
  filename: string
}

// F12 (REQ-7 / REQ-8): una fila persistida por el backend, devuelta por
// GET /api/chat/history. Coincide con la forma del payload que arma
// app/api/chat.py::chat_history.
export interface ChatHistoryMessage {
  id: number
  role: 'user' | 'assistant' | 'system'
  content: string
  citations: RagSource[]
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
  // F13: el backend emite un evento ``attachment`` despues del ultimo
  // token y antes del done cuando el agente renderizo un diagrama
  // Mermaid. El callback recibe el payload publico (sin storage_path).
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

  if (eventName === 'attachment' && rawData && callbacks.onAttachment) {
    try {
      callbacks.onAttachment(JSON.parse(rawData) as Attachment)
    } catch {
      // Si viene mal formado, lo descartamos — el resto del stream sigue.
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
  if (!Array.isArray(payload.messages)) return []

  // PR #76 review fix #6a: apply ``_normaliseHistoryAttachments`` to every
  // row before handing the array to the chatStore. Pre-F13 rows have no
  // ``attachments`` column at all (so ``row.attachments`` is undefined);
  // corrupted transport payloads could deliver ``null``, a string, or a
  // dict instead of the expected array — passing those through raw
  // crashes the renderer's ``message.attachments.map(...)`` downstream.
  // The helper already lives at the bottom of this file and is exported
  // (see the export modifier on its declaration); this is the call-site
  // it was designed for.
  return payload.messages.map((row) => ({
    ...row,
    attachments: _normaliseHistoryAttachments(row.attachments),
  }))
}

// F13 history-parsing helper: defensively coerce a row's ``attachments``
// field into the typed ``Attachment[]`` shape. Older rows (pre-F13) will
// not have the column; missing / non-array values are normalised to ``[]``.
//
// Public so the test suite (frontend/src/api/__tests__/chat.test.ts) can
// exercise the contract directly. PR #76 review fix #6a: previously
// declared but never called from ``fetchChatHistory`` — that meant an
// unknown-shape value (``null`` from a pre-F13 row, a string from a
// legacy schema, or a dict the backend forgot to wrap in an array)
// would land verbatim in the chatStore and crash the renderer when it
// tried to map over ``message.attachments``.
export function _normaliseHistoryAttachments(
  raw: unknown,
): Attachment[] {
  if (!Array.isArray(raw)) return []
  return raw.filter(
    (item): item is Attachment =>
      typeof item === 'object' &&
      item !== null &&
      (item as Attachment).kind === 'screenshot' &&
      typeof (item as Attachment).url === 'string'
  )
}