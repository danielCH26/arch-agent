import { authStore } from '../stores/authStore'
import { apiFetch, ApiError } from './client'

export interface CitationSource {
  type: 'curated_catalog' | 'source_upload'
  label: string
  filename: string | null
}

export interface ProposalCitation {
  pattern_id: number | null
  pattern_name: string | null
  similarity: number | null
  // Backend caps the snippet to 240 chars; useful for tooltips in CitationList.
  snippet?: string | null
  // HU8: number the LLM uses as `[n]` inside the proposal markdown.
  index?: number | null
  category?: string | null
  chunk_type?: string | null
  source?: CitationSource | null
  // `/api/patterns/{id}` -- lets the user read the full indexed text.
  verify_url?: string | null
  // True when at least one `[n]` in the proposal references this source.
  cited?: boolean
}

export interface ProposalJustification {
  decisions_total: number
  decisions_cited: number
  coverage: number
  cites_patterns: boolean
  cited_indices: number[]
  invalid_refs: number[]
  uncited_decisions: { section: string; text: string }[]
}

export interface PatternChunk {
  id: number
  chunk_type: string
  chunk_text: string
  source: string
}

export interface PatternDetail {
  id: number
  pattern_name: string
  category: string | null
  description: string | null
  use_cases: string | null
  tradeoffs: { ventajas?: string[]; desventajas?: string[] } | null
  when_not_to_use: string | null
  decision_signals: unknown[] | null
  chunks: PatternChunk[]
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
  justification?: ProposalJustification | null
}

export interface ProposalDecisionResponse {
  proposal_id: number
  lifecycle: 'approved' | 'rejected'
  current_phase: string | null
  phase_ready: boolean
}

export type ProposalDecision = 'approve' | 'modify' | 'reject'

// --- SSE streaming ---------------------------------------------------------

interface ProposalStreamCallbacks {
  onToken: (token: string) => void
  onSources: (citations: ProposalCitation[]) => void
  onDone: (
    proposalId: number,
    citations: ProposalCitation[],
    justification: ProposalJustification | null,
  ) => void
  onError: (error: string) => void
}

interface ProposalStreamEndpoints {
  generate: '/api/proposals/generate'
  modify: (id: number) => string
}

const ENDPOINTS: ProposalStreamEndpoints = {
  generate: '/api/proposals/generate',
  modify: (id: number) => `/api/proposals/${id}/modify`,
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
        justification?: ProposalJustification
      }
      callbacks.onDone(
        parsed.proposal_id,
        parsed.citations ?? [],
        parsed.justification ?? null,
      )
    } catch {
      callbacks.onError('Malformed SSE done payload')
    }
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

/**
 * Open an SSE stream against either the generate or modify endpoint.
 *
 * Mirrors `createChatStream` (api/chat.ts) so the parsing pipeline is the
 * single source of truth for both chat and proposals.
 */
export function createProposalStream(
  endpoint: 'generate' | 'modify',
  payload: { project_id: number; feedback?: string; proposal_id?: number },
  callbacks: ProposalStreamCallbacks,
): () => void {
  const { onToken, onSources, onDone, onError } = callbacks
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
          const shouldStop = dispatchProposalSSE(event, {
            onToken,
            onSources,
            onDone,
            onError,
          })
          if (shouldStop) return
        }
      }

      if (buffer.trim()) {
        const shouldStop = dispatchProposalSSE(buffer, {
          onToken,
          onSources,
          onDone,
          onError,
        })
        if (shouldStop) return
      }

      // Stream ended without explicit done -- treat as error so the UI can
      // show a banner (matching chat.ts behaviour).
      onError('Stream ended without done event')
    } catch (err) {
      if (err instanceof Error && err.name === 'AbortError') {
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

/** HU8: full pattern (all indexed chunks + source) behind a citation. */
export async function getPatternDetail(patternId: number): Promise<PatternDetail> {
  return apiFetch<PatternDetail>(`/api/patterns/${patternId}`)
}
