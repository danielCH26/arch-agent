/**
 * HU10 v2 approvals store.
 *
 * Derives `pendingDecision` from the `GET /api/projects/{id}/phases`
 * response (REQ-SA-12, REQ-SA-26). The frontend `<ChatWindow>` calls
 * `fetchHistory(projectId)` on mount AND after every chat response so
 * the store is the single source of truth for "is there a pending
 * decision for this project's current phase?".
 *
 * REQ-SA-29 / REQ-SA-34: typed `ApiConflictError` for 409 responses.
 * Callers `instanceof` the error rather than parsing strings.
 */

import { create } from 'zustand'
import {
  ApiConflictError,
  decidePhase,
  type PhaseDecisionAction,
  type PhaseDecisionRequest,
  type PhaseDecisionResponse,
} from '../api/approvals'
import { getPhases, type PendingDecision, type PhasesResponse } from '../api/phases'

export type Phase = string

export interface DecisionRecord {
  decisionId: number
  phase: Phase
  decidedAt: string
  action: PhaseDecisionAction
  idempotent: boolean
}

interface ApprovalsState {
  /** Top-level pending decision keyed by phase. */
  pendingByPhase: Record<Phase, PendingDecision | null>
  /** Cached history of decisions recorded in this session. */
  historyByPhase: Record<Phase, DecisionRecord | null>
  /** Current project id for re-fetch convenience. */
  currentProjectId: number | null
  /** Last phases fetch response (full payload). */
  phases: PhasesResponse | null
  /** True while a network call is in flight. */
  loading: boolean
  /** Last error surfaced to the UI (string or typed). */
  error: string | null

  fetchHistory: (projectId: number) => Promise<void>
  /** REQ-SA-26.2: also re-fetch after every chat response so the store
   * stays in sync even when the SSE consumer didn't fire. */
  refresh: () => Promise<void>

  /** REQ-SA-13, REQ-SA-15: record a decision and update the store. */
  decide: (
    projectId: number,
    phase: Phase,
    body: PhaseDecisionRequest,
  ) => Promise<PhaseDecisionResponse>

  /** Clear the error after the UI has shown it. */
  clearError: () => void
}

const initialPendingByPhase = (): Record<Phase, PendingDecision | null> => ({})

export const useApprovalsStore = create<ApprovalsState>()((set, get) => ({
  pendingByPhase: initialPendingByPhase(),
  historyByPhase: {},
  currentProjectId: null,
  phases: null,
  loading: false,
  error: null,

  fetchHistory: async (projectId: number) => {
    set({ loading: true, error: null, currentProjectId: projectId })
    try {
      const response = await getPhases(projectId)
      const next: Record<Phase, PendingDecision | null> = { ...get().pendingByPhase }
      if (response.pending_decision) {
        next[response.pending_decision.phase] = response.pending_decision
      }
      set({
        phases: response,
        pendingByPhase: next,
        loading: false,
      })
    } catch (err) {
      set({
        error: err instanceof Error ? err.message : 'fetchHistory failed',
        loading: false,
      })
    }
  },

  refresh: async () => {
    const projectId = get().currentProjectId
    if (projectId !== null) {
      await get().fetchHistory(projectId)
    }
  },

  decide: async (projectId, phase, body) => {
    set({ error: null })
    try {
      const response = await decidePhase(projectId, phase, body)
      // Optimistically clear the pending marker for this phase; the next
      // fetchHistory call will confirm.
      const nextPending = { ...get().pendingByPhase, [phase]: null }
      const nextHistory = {
        ...get().historyByPhase,
        [phase]: {
          decisionId: response.decision_id,
          phase,
          decidedAt: response.decided_at,
          action: body.action,
          idempotent: response.idempotent,
        },
      }
      set({ pendingByPhase: nextPending, historyByPhase: nextHistory })
      // Re-sync from the canonical source after a successful write.
      void get().fetchHistory(projectId)
      return response
    } catch (err) {
      if (err instanceof ApiConflictError) {
        set({ error: err.message })
      } else {
        set({
          error: err instanceof Error ? err.message : 'decide failed',
        })
      }
      throw err
    }
  },

  clearError: () => set({ error: null }),
}))

// Back-compat alias -- existing imports may use either name.
export const approvalsStore = useApprovalsStore