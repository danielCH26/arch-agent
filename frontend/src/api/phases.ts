/**
 * HU10 v2 typed client for `GET /api/projects/{id}/phases`.
 *
 * Returns the per-project phase list + a top-level `pending_decision` that
 * the frontend `approvalsStore` uses to mount `<PhaseActions>` from a
 * fetch path (defense-in-depth with the SSE `event: phase_locked`
 * consumer; REQ-SA-12, REQ-SA-26).
 *
 * This file lives separately from `api/approvals.ts` because the
 * `/phases` endpoint is a *read* path that surfaces mount signal data,
 * while `/decision` is the *write* path that needs typed-error handling.
 */

import { apiFetch } from './client'

export interface PendingDecision {
  phase: string
  /** ISO-8601 UTC; null when no decision is on file. */
  since: string | null
  /** Past-tense DB value: 'approved' | 'modified' | 'rejected' | null. */
  last_decision: string | null
  /** ISO-8601 UTC. */
  last_decided_at: string | null
}

export interface PhaseListEntry {
  phase: string
  label: string
  /** 'current' | 'approved' | 'pending'. */
  status: 'current' | 'approved' | 'pending' | string
}

export interface PhasesResponse {
  phases: PhaseListEntry[]
  current_phase: string
  phase_ready: boolean
  available_phases: string[]
  /** Top-level mount signal for `<PhaseActions>` (REQ-SA-12, REQ-SA-26). */
  pending_decision: PendingDecision | null
}

export async function getPhases(projectId: number): Promise<PhasesResponse> {
  return apiFetch<PhasesResponse>(`/api/projects/${projectId}/phases`)
}