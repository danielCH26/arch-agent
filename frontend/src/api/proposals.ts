import { authStore } from '../stores/authStore'
import { apiFetch, ApiError } from './client'

export interface ProposalCitation {
  pattern_id: number | null
  pattern_name: string | null
  similarity: number | null
  source_role?: 'primary' | 'consulted_not_cited'
  // Backend caps the snippet to 240 chars; useful for tooltips in CitationList.
  snippet?: string | null
}

export interface ProposalOut {
  id: number
  project_id: number
  iteration: number
  content: string
  citations: ProposalCitation[]
  feedback: string | null
  lifecycle: 'proposed' | 'approved' | 'rejected'
  created_at: string
}

export interface ProposalDecisionResponse {
  proposal_id: number
  lifecycle: 'approved' | 'rejected'
  current_phase: string | null
  phase_ready: boolean
}

export type ProposalDecision = 'approve' | 'modify' | 'reject'

/**
 * Evento SSE `progress` (F19). Aditivo: el backend lo emite al iniciar cada
 * etapa y, durante la redacción, como máximo una vez por segundo.
 */
export type ProposalProgressStage =
  | 'context'
  | 'retrieval'
  | 'generating'
  | 'saving'

export interface ProposalProgress {
  stage: ProposalProgressStage
  /** 0-100, estimado; llega a 100 solo cuando se emite `done`. */
  percent: number
  message: string
  /** Tiempo transcurrido en el servidor desde que arrancó la generación. */
  elapsed_ms: number
  /**
   * Tope de tiempo del servidor en segundos, o null si está desactivado.
   * Informativo: la UI no lo muestra (solo el tiempo transcurrido).
   */
  budget_s: number | null
  chars?: number
}

/**
 * Metadatos estructurados del evento SSE `error` (F19).
 *
 * El backend emite `{ message, code, retryable }`. La UI decide el reintento
 * con `retryable` / `code`, NUNCA leyendo `message`: ese texto es para humanos
 * y puede cambiar de redacción sin avisar. `code` es un string abierto para que
 * el backend pueda añadir códigos nuevos sin romper un front viejo.
 */
export interface ProposalErrorInfo {
  /** p. ej. `timeout`, `save_timeout`, `llm_stream_failed`, `rejected`. */
  code: string
  /** true solo si repetir la misma petición tiene sentido (corte transitorio). */
  retryable: boolean
}

// --- SSE streaming ---------------------------------------------------------

interface ProposalStreamCallbacks {
  onToken: (token: string) => void
  onSources: (citations: ProposalCitation[]) => void
  /** Opcional: un front/consumidor que no muestre progreso puede omitirlo. */
  onProgress?: (progress: ProposalProgress) => void
  onDone: (
    proposalId: number,
    citations: ProposalCitation[],
    iteration?: number,
  ) => void
  /**
   * `info` solo llega si el error vino del evento SSE `error` estructurado.
   * Errores del cliente (HTTP, red, stream cortado) llegan sin `info`: no se
   * ofrece reintento automático porque no sabemos si la propuesta se guardó.
   */
  onError: (error: string, info?: ProposalErrorInfo) => void
}

interface ProposalStreamEndpoints {
  generate: '/api/proposals/generate'
  modify: (id: number) => string
}

const ENDPOINTS: ProposalStreamEndpoints = {
  generate: '/api/proposals/generate',
  modify: (id: number) => `/api/proposals/${id}/modify`,
}

/**
 * Normaliza el payload del evento `error`: objeto estructurado (actual) o
 * string suelto (backend viejo / otro productor). Un string no trae `info`, así
 * que nunca habilita el reintento: antes se adivinaba con un regex sobre el
 * texto y cualquier cambio de redacción lo rompía en silencio.
 */
function parseErrorPayload(rawData: string): [string, ProposalErrorInfo?] {
  let payload: unknown = rawData
  try {
    payload = JSON.parse(rawData)
  } catch {
    // texto plano: se muestra tal cual
  }
  if (typeof payload === 'string') return [payload]
  if (payload !== null && typeof payload === 'object') {
    const { message, code, retryable } = payload as Record<string, unknown>
    const text = typeof message === 'string' && message ? message : 'Unknown error'
    return [
      text,
      {
        code: typeof code === 'string' && code ? code : 'unknown',
        retryable: retryable === true,
      },
    ]
  }
  return [rawData]
}

function dispatchProposalSSE(
  rawEvent: string,
  callbacks: ProposalStreamCallbacks,
): boolean {
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

  if (eventName === 'progress' && rawData) {
    try {
      callbacks.onProgress?.(JSON.parse(rawData) as ProposalProgress)
    } catch {
      // Un progreso ilegible no debe tumbar la generación.
    }
    return false
  }

  if (eventName === 'sources' && rawData) {
    try {
      callbacks.onSources(JSON.parse(rawData) as ProposalCitation[])
    } catch {
      callbacks.onSources([])
    }
    return false
  }

  if (eventName === 'token' && rawData) {
    try {
      const parsed = JSON.parse(rawData)
      callbacks.onToken(parsed.delta || parsed)
    } catch {
      callbacks.onToken(rawData)
    }
    return false
  }

  if (eventName === 'done' && rawData) {
    try {
      const parsed = JSON.parse(rawData) as {
        proposal_id: number
        citations: ProposalCitation[]
        iteration?: number
      }
      callbacks.onDone(parsed.proposal_id, parsed.citations ?? [], parsed.iteration)
    } catch {
      callbacks.onError('Malformed SSE done payload')
    }
    return true
  }

  if (eventName === 'error' && rawData) {
    callbacks.onError(...parseErrorPayload(rawData))
    return true
  }

  return false
}

/**
 * Open an SSE stream against either the generate or modify endpoint.
 *
 * Devuelve una función que ABORTA el fetch (F19, "Cancelar"): al cerrarse la
 * conexión el backend deja de escribir y cierra el stream del LLM. Si ya estaba
 * guardando, la propuesta puede quedar guardada igualmente (el hilo de la BD no
 * se aborta a la fuerza). Un abort es silencioso: no dispara `onError`.
 *
 * Mirrors `createChatStream` (api/chat.ts) so the parsing pipeline is the
 * single source of truth for both chat and proposals.
 */
export function createProposalStream(
  endpoint: 'generate' | 'modify',
  payload: { project_id: number; feedback?: string; proposal_id?: number },
  callbacks: ProposalStreamCallbacks,
): () => void {
  const { onError } = callbacks
  const token = authStore.getState().token
  const url =
    endpoint === 'generate'
      ? ENDPOINTS.generate
      : ENDPOINTS.modify(payload.proposal_id as number)

  const controller = new AbortController()
  const signal = controller.signal

  void (async () => {
    try {
      const response = await fetch(url, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify(
          endpoint === 'generate'
            ? { project_id: payload.project_id }
            : {
                feedback: payload.feedback,
              },
        ),
        signal,
      })

      if (!response.ok) {
        const data = await response.json().catch(() => ({}))
        const message = (data.detail as string) || 'Proposal request failed'
        onError(message)
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
          const shouldStop = dispatchProposalSSE(event, callbacks)
          if (shouldStop) return
        }
      }

      if (buffer.trim()) {
        const shouldStop = dispatchProposalSSE(buffer, callbacks)
        if (shouldStop) return
      }

      // Stream ended without explicit done -- treat as error so the UI can
      // show a banner (matching chat.ts behaviour).
      onError('Stream ended without done event')
    } catch (err) {
      // Cancelación del usuario (F19). Se mira `name` sin exigir `instanceof
      // Error`: un DOMException de abort no siempre hereda de Error según el
      // entorno/realm, y reportarlo como fallo mostraría un error falso.
      if ((err as { name?: string } | null)?.name === 'AbortError') {
        return
      }
      onError(err instanceof Error ? err.message : 'Unknown error')
    }
  })()

  return () => controller.abort()
}

// --- JSON helpers (decide + getById) -------------------------------------


export async function decideProposal(
  proposalId: number,
  decision: ProposalDecision,
  comment?: string,
): Promise<ProposalDecisionResponse> {
  try {
    return await apiFetch<ProposalDecisionResponse>(
      `/api/proposals/${proposalId}/decide`,
      {
        method: 'POST',
        body: JSON.stringify({ decision, comment }),
      },
    )
  } catch (err) {
    if (err instanceof ApiError) {
      throw err
    }
    throw new ApiError(
      0,
      err instanceof Error ? err.message : 'decideProposal failed',
    )
  }
}

export async function getProposal(proposalId: number): Promise<ProposalOut> {
  return apiFetch<ProposalOut>(`/api/proposals/${proposalId}`)
}

/**
 * Última propuesta viva (proposed/approved) del proyecto, o null si no hay.
 * Sirve para rehidratar la tarjeta al recargar / volver a entrar a la fase:
 * antes la propuesta solo vivía en memoria del front.
 */
export async function getLatestProposal(projectId: number): Promise<ProposalOut | null> {
  return apiFetch<ProposalOut | null>(`/api/projects/${projectId}/proposals/latest`)
}

/** Todas las versiones persistidas, de más reciente a más antigua. */
export async function getProposalHistory(projectId: number): Promise<ProposalOut[]> {
  return apiFetch<ProposalOut[]>(`/api/projects/${projectId}/proposals`)
}
