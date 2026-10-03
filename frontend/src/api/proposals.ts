import { authStore } from '../stores/authStore'
import { ApiError, apiFetch, apiUrl, errorMessageFromResponse, handleUnauthorized, safeFetch, streamErrorMessage } from './client'

export interface ProposalCitation {
  pattern_id: number | null
  pattern_name: string | null
  similarity: number | null
  // 'consulted_not_cited' solo existe en propuestas guardadas antes de renombrarlo.
  source_role?: 'primary' | 'tradeoff_option' | 'consulted_not_cited'
  snippet?: string | null
  tradeoffs?: {
    ventajas?: string[]
    desventajas?: string[]
  }
}

export type ProposalLifecycle = 'proposed' | 'approved' | 'rejected'
export type ProposalDecision = 'approve' | 'reject'

export interface ProposalOut {
  id: number
  project_id: number
  iteration: number
  content: string
  citations: ProposalCitation[]
  feedback: string | null
  lifecycle: ProposalLifecycle
  created_at: string
}

export interface ProjectProposalState {
  approved: boolean
  approved_at: string | null
  approval_id: number | null
  proposal_snapshot_chars: number
  last_decision: string | null
  // Tope de iteraciones del backend (PROPOSAL_MAX_ITER). Opcional: un backend
  // anterior no lo envía y entonces el límite solo se aplica en el servidor.
  max_iterations?: number
}

export interface ProjectProposalDecisionResponse {
  decision: 'approve' | 'modify' | 'reject'
  phase_ready: boolean
  approval_id: number | null
  proposal_snapshot_chars: number
  message: string
}

export interface ProposalDecisionResponse {
  proposal_id: number
  lifecycle: 'approved' | 'rejected'
  current_phase: string | null
  phase_ready: boolean
}

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

interface ProposalStreamCallbacks {
  onToken: (token: string) => void
  onSources: (citations: ProposalCitation[]) => void
  /** Opcional: un front/consumidor que no muestre progreso puede omitirlo. */
  onProgress?: (progress: ProposalProgress) => void
  onDone: (proposalId: number, citations: ProposalCitation[]) => void
  // `status`: código HTTP cuando el error viene de la respuesta (p. ej. 409).
  onError: (message: string, status?: number) => void
}

function parseEvent(rawEvent: string, callbacks: ProposalStreamCallbacks): boolean {
  let name = 'message'
  const data: string[] = []
  for (const line of rawEvent.split('\n')) {
    if (line.startsWith('event:')) name = line.slice(6).trim()
    if (line.startsWith('data:')) data.push(line.slice(5).trim())
  }
  const payload = data.join('\n')

  if (name === 'progress' && payload) {
    try {
      callbacks.onProgress?.(JSON.parse(payload) as ProposalProgress)
    } catch {
      // Un progreso ilegible no debe tumbar la generación.
    }
    return false
  }
  if (name === 'sources') {
    try { callbacks.onSources(JSON.parse(payload) as ProposalCitation[]) } catch { callbacks.onSources([]) }
    return false
  }
  if (name === 'token' && payload) {
    try {
      const parsed = JSON.parse(payload)
      callbacks.onToken(parsed.delta || parsed)
    } catch { callbacks.onToken(payload) }
    return false
  }
  if (name === 'done') {
    try {
      const parsed = JSON.parse(payload) as { proposal_id: number; citations?: ProposalCitation[] }
      callbacks.onDone(parsed.proposal_id, parsed.citations ?? [])
    } catch { callbacks.onError('La propuesta terminó con un formato inválido.') }
    return true
  }
  if (name === 'error') {
    let parsed: unknown = payload
    try { parsed = JSON.parse(payload) } catch { /* texto plano */ }
    callbacks.onError(streamErrorMessage(parsed, 'No se pudo generar la propuesta.'))
    return true
  }
  return false
}

/**
 * Abre el stream SSE de generar o modificar.
 *
 * Devuelve una función que ABORTA el fetch (F19, "Cancelar"): al cerrarse la
 * conexión el backend deja de escribir, cierra el stream del LLM y no persiste
 * nada. Un abort es silencioso: no dispara `onError`.
 */
export function createProposalStream(
  mode: 'generate' | 'modify',
  payload: { projectId: number; proposalId?: number; feedback?: string },
  callbacks: ProposalStreamCallbacks,
): () => void {
  const controller = new AbortController()
  const token = authStore.getState().token
  const url = apiUrl(mode === 'generate'
    ? '/api/proposals/generate'
    : `/api/proposals/${payload.proposalId}/modify`)
  const body = mode === 'generate'
    ? { project_id: payload.projectId }
    : { feedback: payload.feedback }

  void (async () => {
    try {
      const response = await safeFetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        body: JSON.stringify(body),
        signal: controller.signal,
      })
      if (response.status === 401) {
        callbacks.onError(handleUnauthorized().message, 401)
        return
      }
      if (!response.ok) {
        const error = await response.json().catch(() => ({}))
        callbacks.onError(errorMessageFromResponse(response.status, error), response.status)
        return
      }
      if (!response.body) {
        callbacks.onError('El servidor no entregó contenido para la propuesta.')
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
          if (event.trim() && parseEvent(event, callbacks)) return
        }
      }
      if (buffer.trim() && parseEvent(buffer, callbacks)) return
      callbacks.onError('La generación terminó antes de completarse.')
    } catch (error) {
      // Cancelación del usuario (F19). Se mira `name` sin exigir `instanceof
      // Error`: un DOMException de abort no siempre hereda de Error según el
      // entorno/realm, y reportarlo como fallo mostraría un error falso.
      if ((error as { name?: string } | null)?.name === 'AbortError') return
      callbacks.onError(
        error instanceof Error ? error.message : 'No se pudo conectar con el servidor.',
        error instanceof ApiError ? error.status : undefined,
      )
    }
  })()

  return () => controller.abort()
}

export function decideProposal(proposalId: number, decision: ProposalDecision, comment?: string) {
  return apiFetch<ProposalDecisionResponse>(`/api/proposals/${proposalId}/decide`, {
    method: 'POST',
    body: JSON.stringify({ decision, comment }),
  })
}

export function getProposal(proposalId: number) {
  return apiFetch<ProposalOut>(`/api/proposals/${proposalId}`)
}

export function getProjectProposalState(projectId: number) {
  return apiFetch<ProjectProposalState>(`/api/projects/${projectId}/proposal`)
}

export function decideProjectProposal(
  projectId: number,
  decision: 'approve' | 'modify' | 'reject',
  options: { feedback?: string; proposalText?: string } = {},
) {
  return apiFetch<ProjectProposalDecisionResponse>(`/api/projects/${projectId}/proposal/decision`, {
    method: 'POST',
    body: JSON.stringify({ decision, feedback: options.feedback, proposal_text: options.proposalText }),
  })
}
