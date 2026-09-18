import { create } from 'zustand'
import {
  PhaseDecisionConflict,
  createRegenerateStream,
  type DecideBody,
  type Decision,
  type DecisionResponse,
  type Phase,
  type PhaseStatusItem,
  type RegenerateBody,
  decidePhase,
  listPhases,
} from '../api/approvals'

/**
 * Cross-phase decision state for HU10 (REQ-SA-21) + HU11 (REQ-SA-25).
 *
 * Mirrors the pattern used by ``frontend/src/stores/chatStore.ts`` and
 * ``frontend/src/stores/proposalsStore.ts``: ``create<State>()((set, get) => ({ ... }))``.
 *
 * The store is intentionally phase-agnostic — each phase has its own slot
 * in ``pendingDecision`` and ``historyByPhase`` so the SPA can show
 * per-phase UI (e.g. <PhaseActions> for the current phase + an audit log
 * for past phases). Re-fetching ``fetchHistory`` replaces the slot atomically
 * so React doesn't see partial state.
 *
 * HU11: ``regeneratingPhase`` tracks the in-flight LLM regenerate per
 * phase; ``regeneratePhase`` action opens an SSE stream against
 * ``/api/projects/{id}/phases/{phase}/regenerate``. On ``done`` we
 * re-fetch history so the new proposal iteration / elicitation summary
 * shows up in ``historyByPhase``. On ``error`` we set ``error`` and
 * clear the in-flight flag — the prior /decision audit row stays in
 * the DB (REQ-SA-25.4) so the UI shows a Reintentar button.
 */
export interface PendingDecision {
  phase: Phase
  action?: 'approve' | 'modify' | 'reject'
}

interface ApprovalsState {
  pendingDecision: Record<Phase, PendingDecision | null>
  historyByPhase: Record<Phase, Decision[]>
  phases: PhaseStatusItem[]
  currentPhase: Phase | null
  loading: boolean
  error: string | null
  // HU11: phase currently being regenerated (null = idle).
  regeneratingPhase: Phase | null

  // Actions
  fetchHistory: (projectId: number | string) => Promise<void>
  setPending: (phase: Phase) => void
  clearPending: (phase: Phase) => void
  decide: (
    projectId: number | string,
    phase: Phase,
    body: DecideBody,
  ) => Promise<DecisionResponse>
  // HU11: open SSE regenerate stream for ``phase`` with user feedback.
  regeneratePhase: (
    projectId: number | string,
    phase: Phase,
    body: RegenerateBody,
  ) => Promise<void>
  reset: () => void
}

const PHASES: Phase[] = [
  'requerimientos',
  'propuesta',
  'refinamiento',
  'revision',
  'final',
]

function emptyPending(): Record<Phase, PendingDecision | null> {
  return PHASES.reduce(
    (acc, p) => {
      acc[p] = null
      return acc
    },
    {} as Record<Phase, PendingDecision | null>,
  )
}

function emptyHistory(): Record<Phase, Decision[]> {
  return PHASES.reduce(
    (acc, p) => {
      acc[p] = []
      return acc
    },
    {} as Record<Phase, Decision[]>,
  )
}

export const approvalsStore = create<ApprovalsState>((set, get) => ({
  pendingDecision: emptyPending(),
  historyByPhase: emptyHistory(),
  phases: [],
  currentPhase: null,
  loading: false,
  error: null,
  regeneratingPhase: null,

  fetchHistory: async (projectId) => {
    set({ loading: true, error: null })
    try {
      const response = await listPhases(projectId)
      const history: Record<Phase, Decision[]> = emptyHistory()
      for (const item of response.phases) {
        if (item.current_decision) {
          history[item.name] = [item.current_decision]
        }
      }
      set({
        phases: response.phases,
        currentPhase: response.current_phase,
        historyByPhase: history,
        loading: false,
      })
    } catch (err) {
      const message =
        err instanceof Error ? err.message : 'Failed to fetch approval history'
      set({ loading: false, error: message })
      throw err
    }
  },

  setPending: (phase) => {
    set((state) => ({
      pendingDecision: { ...state.pendingDecision, [phase]: { phase } },
    }))
  },

  clearPending: (phase) => {
    set((state) => ({
      pendingDecision: { ...state.pendingDecision, [phase]: null },
    }))
  },

  decide: async (projectId, phase, body) => {
    set((state) => ({
      pendingDecision: {
        ...state.pendingDecision,
        [phase]: { phase, action: body.action },
      },
      error: null,
    }))
    try {
      const response = await decidePhase(projectId, phase, body)
      // Optimistically prepend the new decision to history; the next
      // fetchHistory() call will reconcile if the server returns more.
      const optimistic: Decision = {
        id: response.decision_id,
        action: response.action,
        feedback: body.feedback ?? null,
        decided_at: response.decided_at,
      }
      set((state) => ({
        historyByPhase: {
          ...state.historyByPhase,
          [phase]: [
            optimistic,
            ...(state.historyByPhase[phase] ?? []).filter(
              (d) => d.id !== response.decision_id,
            ),
          ],
        },
        pendingDecision: {
          ...state.pendingDecision,
          [phase]: null,
        },
      }))
      // Re-sync from server so any cascade effects (current_phase update,
      // phase_ready flip) are reflected. Errors here are non-fatal: the
      // optimistic update already succeeded.
      try {
        await get().fetchHistory(projectId)
      } catch {
        // Ignore -- the optimistic history is already correct.
      }
      return response
    } catch (err) {
      if (err instanceof PhaseDecisionConflict) {
        // 409: the server has a more recent decision. Re-sync without
        // crashing the SPA; the toast / inline error comes from the
        // component layer.
        try {
          await get().fetchHistory(projectId)
        } catch {
          // ignore -- store stays usable
        }
        set((state) => ({
          pendingDecision: {
            ...state.pendingDecision,
            [phase]: null,
          },
          error: `Conflicto: ya existe una decisión (${err.current_decision}).`,
        }))
        throw err
      }
      const message =
        err instanceof Error ? err.message : 'decide failed'
      set({ error: message })
      throw err
    }
  },

  // HU11 (REQ-SA-25): open SSE regenerate stream. Mirrors the chat SSE
  // pattern (chatStore.ts:50-129) — AbortController-based cleanup so
  // component unmount doesn't leak event listeners. The decision audit
  // row was already written by HU10's /decision call; on regenerate
  // failure we surface the error but do NOT roll back the decision —
  // the user can Reintentar from the UI (REQ-SA-25.4).
  regeneratePhase: async (projectId, phase, body) => {
    set({ regeneratingPhase: phase, error: null })
    return new Promise<void>((resolve) => {
      createRegenerateStream(projectId, phase, body, {
        onSources: () => {
          // Future: surface RAG sources in a sidebar. No-op for now —
          // the chat/proposal UIs already cover the same pattern.
        },
        onToken: () => {
          // Tokens stream into the chat timeline via chatStore; we
          // intentionally do NOT mirror them into approvalsStore so the
          // audit row reflects only structured decisions.
        },
        onDone: async () => {
          set({ regeneratingPhase: null })
          try {
            await get().fetchHistory(projectId)
          } catch {
            // Best-effort — the regenerate itself succeeded.
          }
          resolve()
        },
        onError: (message) => {
          set({
            regeneratingPhase: null,
            error: `Regenerate failed for ${phase}: ${message}`,
          })
          resolve()
        },
      })
    })
  },

  reset: () => {
    set({
      pendingDecision: emptyPending(),
      historyByPhase: emptyHistory(),
      phases: [],
      currentPhase: null,
      loading: false,
      error: null,
      regeneratingPhase: null,
    })
  },
}))