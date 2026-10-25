/**
 * HU10 v2 typed client for `POST /api/projects/{id}/phase/{phase}/decision`.
 *
 * Closes PR #78 blocker #4 by reading the typed 409 body shape from
 * `err.data.detail.*` (FastAPI wraps in `detail`) and surfacing a typed
 * `ApiConflictError` (REQ-SA-29, REQ-SA-34). The body shape is:
 *
 *   409 → { detail: { error: 'phase_mismatch' | 'decision_conflict' | ...,
 *                    current_phase, requested_phase?,
 *                    current_decision?, decided_at?, decision_id? } }
 *
 * Per REQ-SA-15, the 200 response shape is:
 *
 *   { decision_id, action, phase, project_id, next_phase, decided_at, idempotent }
 */

import { ApiError, apiFetch } from './client'

// ---------------------------------------------------------------------------
// Body shapes
// ---------------------------------------------------------------------------

export type PhaseDecisionAction = 'approve' | 'modify' | 'reject'

export interface PhaseDecisionRequest {
  action: PhaseDecisionAction
  feedback?: string | null
  payload?: Record<string, unknown> | null
  idempotency_key?: string | null
}

export interface PhaseDecisionResponse {
  decision_id: number
  action: PhaseDecisionAction
  phase: string
  project_id: number
  next_phase: string | null
  decided_at: string
  idempotent: boolean
}

// ---------------------------------------------------------------------------
// Typed 409 body
// ---------------------------------------------------------------------------

export type ConflictReason =
  | 'phase_mismatch'
  | 'decision_conflict'
  | 'phase_not_approved'
  | 'wrong_owner'
  | 'phase_decision_error'
  | 'validation_error'
  | 'endpoint_removed'

export interface ConflictDetail {
  error?: ConflictReason | string
  current_phase?: string
  requested_phase?: string
  current_decision?: string
  decided_at?: string | null
  decision_id?: number
  phase?: string
  message?: string
  available_phases?: string[]
  replacement?: string
  canonical_endpoint?: string
  owner?: string
}

/**
 * REQ-SA-29, REQ-SA-34: typed error class for 409 responses. Frontend code
 * should `instanceof` this rather than parsing strings. The body shape is
 * what the FastAPI server emits under `err.data.detail` -- never
 * `err.data` directly (PR #78 blocker #4).
 */
export class ApiConflictError extends Error {
  public readonly status: number
  public readonly detail: ConflictDetail

  constructor(status: number, detail: ConflictDetail) {
    super(
      `ApiConflictError(${detail.error ?? 'unknown'}): ${
        detail.current_phase ?? detail.message ?? 'phase conflict'
      }`,
    )
    this.name = 'ApiConflictError'
    this.status = status
    this.detail = detail
  }

  /** Convenience: returns the conflicting phase or null if missing. */
  get currentPhase(): string | null {
    return this.detail.current_phase ?? null
  }

  /** Convenience: returns the original decision id (if the server gave one). */
  get decisionId(): number | null {
    return this.detail.decision_id ?? null
  }
}

// ---------------------------------------------------------------------------
// Endpoint
// ---------------------------------------------------------------------------

export async function decidePhase(
  projectId: number,
  phase: string,
  body: PhaseDecisionRequest,
): Promise<PhaseDecisionResponse> {
  try {
    return await apiFetch<PhaseDecisionResponse>(
      `/api/projects/${projectId}/phase/${phase}/decision`,
      {
        method: 'POST',
        body: JSON.stringify(body),
      },
    )
  } catch (err) {
    if (err instanceof ApiError && (err.status === 409 || err.status === 400)) {
      // REQ-SA-29: read `err.data.detail.*` (FastAPI wraps in `detail`).
      // Tolerate `err.data?.detail ?? err.data` for callers that may have
      // an older backend that surfaces the typed body at the top level.
      const data = (err.data ?? {}) as { detail?: ConflictDetail }
      const detail: ConflictDetail =
        (data.detail as ConflictDetail | undefined) ?? (err.data as ConflictDetail)
      throw new ApiConflictError(err.status, detail ?? {})
    }
    throw err
  }
}