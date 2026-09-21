import { apiFetch, ApiError } from './client'

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
}

export interface PhaseListResponse {
  phases: PhaseStatusItem[]
  current_phase: Phase
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