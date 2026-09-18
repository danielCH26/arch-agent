import { apiFetch, ApiError } from './client'
import { authStore } from '../stores/authStore'

/**
 * Typed REST client for the HU10 generic per-phase decision endpoint.
 *
 * Mirrors the contract documented in
 * ``openspec/specs/staged-approvals/spec.md`` REQ-SA-13/14/15/22.
 */

export type Phase =
  | 'requerimientos'
  | 'propuesta'
  | 'refinamiento'
  | 'revision'
  | 'final'

export type DecisionAction = 'approve' | 'modify' | 'reject'

export interface DecideBody {
  action: DecisionAction
  feedback?: string
  payload?: Record<string, unknown>
}

export interface Decision {
  id: number
  action: string
  feedback?: string | null
  decided_at?: string | null
}

export interface DecisionResponse {
  decision_id: number
  project_id: number
  phase: Phase
  action: DecisionAction
  next_phase: Phase | null
  decided_at: string
  idempotent: boolean
}

export interface PhaseStatusItem {
  name: Phase
  label: string
  status: 'active' | 'approved' | 'pending'
  ready: boolean
  current_decision: Decision | null
  // HU11 (REQ-SA-26): true iff a past-phase modify exists whose
  // created_at is newer than the latest approve of any downstream phase.
  // Frontend treats undefined as false (HU10 backward compat).
  stale?: boolean
}

export interface PhaseListResponse {
  phases: PhaseStatusItem[]
  current_phase: Phase
}

/**
 * HU11 (REQ-SA-25): regenerate request body for the per-phase SSE endpoint.
 */
export interface RegenerateBody {
  feedback: string
  payload?: Record<string, unknown>
}

/**
 * HU11: typed error for past-phase modify rejected by the F05 guard
 * (REQ-SA-28) or the regenerate endpoint (final phase / phase >= current).
 */
export class PhaseRegenerateConflict extends Error {
  constructor(public detail: string) {
    super(`phase regenerate rejected: ${detail}`)
    this.name = 'PhaseRegenerateConflict'
  }
}

export async function decidePhase(
  projectId: number | string,
  phase: Phase,
  body: DecideBody,
): Promise<DecisionResponse> {
  try {
    return await apiFetch<DecisionResponse>(
      `/api/projects/${projectId}/phase/${phase}/decision`,
      {
        method: 'POST',
        body: JSON.stringify(body),
      },
    )
  } catch (err) {
    if (err instanceof ApiError) {
      // 409 Conflict: surface the structured body so the store can re-sync
      // state from the server's current_decision.
      if (err.status === 409) {
        throw new PhaseDecisionConflict(
          (err.data as { current_decision?: string })?.current_decision ?? 'unknown',
          (err.data as { decided_at?: string })?.decided_at ?? null,
        )
      }
      throw err
    }
    throw new ApiError(
      0,
      err instanceof Error ? err.message : 'decidePhase failed',
    )
  }
}

export async function listPhases(
  projectId: number | string,
): Promise<PhaseListResponse> {
  return apiFetch<PhaseListResponse>(`/api/projects/${projectId}/phases`)
}

/**
 * HU11 (REQ-SA-25): open an SSE stream against
 * ``POST /api/projects/{id}/phases/{phase}/regenerate``.
 *
 * Event shape matches the existing chat / proposal streams:
 * ``event: sources | token* | done | error``. The frontend's
 * ``dispatchSSEEvent`` parser can be reused verbatim (no new branch).
 */
export interface RegenerateStreamCallbacks {
  onSources?: (sources: unknown[]) => void
  onToken?: (token: string) => void
  onDone?: (payload: Record<string, unknown>) => void
  onError?: (message: string) => void
}

function dispatchRegenerateSSE(
  rawEvent: string,
  callbacks: RegenerateStreamCallbacks,
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
      callbacks.onSources?.(JSON.parse(rawData) as unknown[])
    } catch {
      callbacks.onSources?.([])
    }
    return false
  }
  if (eventName === 'token' && rawData) {
    try {
      const data = JSON.parse(rawData)
      callbacks.onToken?.(typeof data === 'string' ? data : data.delta ?? '')
    } catch {
      callbacks.onToken?.(rawData)
    }
    return false
  }
  if (eventName === 'done' && rawData) {
    try {
      callbacks.onDone?.(JSON.parse(rawData) as Record<string, unknown>)
    } catch {
      callbacks.onError?.('Malformed SSE done payload')
    }
    return true
  }
  if (eventName === 'error' && rawData) {
    try {
      callbacks.onError?.(JSON.parse(rawData) as string)
    } catch {
      callbacks.onError?.(rawData)
    }
    return true
  }
  return false
}

export function createRegenerateStream(
  projectId: number | string,
  phase: Phase,
  body: RegenerateBody,
  callbacks: RegenerateStreamCallbacks,
): () => void {
  const token = authStore.getState().token

  const controller = new AbortController()
  const signal = controller.signal

  void (async () => {
    try {
      const response = await fetch(
        `/api/projects/${projectId}/phases/${phase}/regenerate`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
          body: JSON.stringify(body),
          signal,
        },
      )

      if (!response.ok) {
        const data = await response.json().catch(() => ({}))
        const detail = (data.detail as string) || 'Regenerate request failed'
        if (response.status === 409) {
          callbacks.onError?.(detail)
        } else {
          callbacks.onError?.(detail)
        }
        return
      }
      if (!response.body) {
        callbacks.onError?.('No response body')
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
          const stop = dispatchRegenerateSSE(event, callbacks)
          if (stop) return
        }
      }
      if (buffer.trim()) {
        const stop = dispatchRegenerateSSE(buffer, callbacks)
        if (stop) return
      }
      callbacks.onError?.('Stream ended without done event')
    } catch (err) {
      if (err instanceof Error && err.name === 'AbortError') {
        return
      }
      callbacks.onError?.(err instanceof Error ? err.message : 'Unknown error')
    }
  })()

  return () => controller.abort()
}

export class PhaseDecisionConflict extends Error {
  constructor(
    public current_decision: string,
    public decided_at: string | null,
  ) {
    super(
      `phase already decided as ${current_decision} at ${decided_at ?? 'unknown'}`,
    )
    this.name = 'PhaseDecisionConflict'
  }
}