import { create } from 'zustand'
import {
  type ProposalCitation,
  type ProposalDecision,
  type ProposalDecisionResponse,
  type ProposalOut,
  createProposalStream,
  decideProposal,
  getProposalHistory,
  getLatestProposal,
  getProposal as fetchProposal,
} from '../api/proposals'

/**
 * Single-source-of-truth for the currently active proposal.
 *
 * Mirrors `frontend/src/stores/chatStore.ts` (Zustand v5 typed form):
 * `create<State>()((set, get) => ({ ... }))`. Action signatures match
 * design.md §6 so this file is the public contract the UI consumes.
 */
export interface Proposal {
  id: number | null
  project_id: number
  iteration: number
  // Streamed markdown accumulator. Promoted to `content` on `done`.
  content_markdown: string
  citations: ProposalCitation[]
  lifecycle: 'proposed' | 'approved' | 'rejected' | 'idle'
  feedback: string | null
  created_at: string | null
}

export type InFlightStatus = 'idle' | 'generating' | 'modifying' | 'deciding'

interface ProposalsState {
  currentProposal: Proposal | null
  /** Draft for the next iteration. The approved/current version stays intact. */
  pendingProposal: Proposal | null
  iterations: Proposal[]
  inFlight: InFlightStatus
  error: string | null

  // Streaming actions
  generate: (projectId: number) => Promise<void>
  modify: (proposalId: number, feedback: string) => Promise<void>

  // Decision action
  decide: (
    proposalId: number,
    decision: Exclude<ProposalDecision, 'modify'>,
    comment?: string,
  ) => Promise<ProposalDecisionResponse>

  // Read helper (used to re-sync after a 409, see design §10)
  refresh: (proposalId: number) => Promise<void>

  // Rehidrata la propuesta viva del proyecto desde el backend (al recargar o
  // volver a entrar a la fase). No toca nada si hay un stream en curso.
  loadLatest: (projectId: number) => Promise<void>

  // Cleanup
  reset: () => void
  clearError: () => void
}

function emptyProposal(projectId: number): Proposal {
  return {
    id: null,
    project_id: projectId,
    iteration: 0,
    content_markdown: '',
    citations: [],
    lifecycle: 'proposed',
    feedback: null,
    created_at: null,
  }
}

function proposalFromOut(out: ProposalOut): Proposal {
  return {
    id: out.id,
    project_id: out.project_id,
    iteration: out.iteration,
    content_markdown: out.content,
    citations: out.citations ?? [],
    lifecycle: out.lifecycle,
    feedback: out.feedback,
    created_at: out.created_at,
  }
}

export const proposalsStore = create<ProposalsState>((set, get) => ({
  currentProposal: null,
  pendingProposal: null,
  iterations: [],
  inFlight: 'idle',
  error: null,

  generate: async (projectId: number) => {
    set({
      inFlight: 'generating',
      error: null,
      currentProposal: emptyProposal(projectId),
      pendingProposal: null,
    })

    createProposalStream(
      'generate',
      { project_id: projectId },
      {
        onSources: (citations) => {
          set((state) =>
            state.currentProposal
              ? { currentProposal: { ...state.currentProposal, citations } }
              : {},
          )
        },
        onToken: (token) => {
          set((state) =>
            state.currentProposal
              ? {
                  currentProposal: {
                    ...state.currentProposal,
                    content_markdown:
                      state.currentProposal.content_markdown + token,
                  },
                }
              : {},
          )
        },
        onDone: (proposalId, citations, iteration) => {
          set((state) => {
            const base = state.currentProposal ?? emptyProposal(projectId)
            const finalized: Proposal = {
              ...base,
              id: proposalId,
              citations,
              // Iteración real guardada en la DB (antes quedaba en 0 y la
              // siguiente modificación se mostraba como "iteración 1").
              iteration: iteration ?? (base.iteration || 1),
              // lifecycle stays 'proposed' until the user clicks Aprobar/Rechazar.
            }
            return {
              currentProposal: finalized,
              pendingProposal: null,
              iterations: [finalized, ...state.iterations],
              inFlight: 'idle',
            }
          })
        },
        onError: (message) => {
          set({ inFlight: 'idle', error: message, pendingProposal: null })
        },
      },
    )
  },

  modify: async (proposalId: number, feedback: string) => {
    // Keep the current iteration visible and immutable while the next one is
    // streamed. Replacing it with an empty draft made feedback appear to erase
    // the proposal until the request finished.
    const current = get().currentProposal
    const prior =
      get().iterations.find((p) => p.id === proposalId) ??
      (current?.id === proposalId ? current : undefined)
    set({
      inFlight: 'modifying',
      error: null,
      pendingProposal: emptyProposal(prior?.project_id ?? 0),
    })

    createProposalStream(
      'modify',
      { project_id: prior?.project_id ?? 0, feedback, proposal_id: proposalId },
      {
        onSources: (citations) => {
          set((state) =>
            state.pendingProposal
              ? { pendingProposal: { ...state.pendingProposal, citations } }
              : {},
          )
        },
        onToken: (token) => {
          set((state) =>
            state.pendingProposal
              ? {
                  pendingProposal: {
                    ...state.pendingProposal,
                    content_markdown:
                      state.pendingProposal.content_markdown + token,
                  },
                }
              : {},
          )
        },
        onDone: (newProposalId, citations, iteration) => {
          set((state) => {
            const base = state.pendingProposal ?? emptyProposal(0)
            const finalized: Proposal = {
              ...base,
              id: newProposalId,
              citations,
              feedback,
              iteration: iteration ?? (prior?.iteration ?? 0) + 1,
            }
            return {
              currentProposal: finalized,
              pendingProposal: null,
              iterations: [
                finalized,
                ...state.iterations.filter((proposal) => proposal.id !== finalized.id),
              ],
              inFlight: 'idle',
            }
          })
        },
        onError: (message) => {
          set({ inFlight: 'idle', error: message, pendingProposal: null })
        },
      },
    )
  },

  decide: async (proposalId, decision, comment) => {
    set({ inFlight: 'deciding', error: null })
    try {
      const response = await decideProposal(proposalId, decision, comment)
      set((state) => {
        const updated: Proposal | null = state.currentProposal
          ? {
              ...state.currentProposal,
              id: response.proposal_id,
              lifecycle: response.lifecycle,
            }
          : null
        return {
          currentProposal: updated,
          iterations: state.iterations.map((p) =>
            p.id === response.proposal_id
              ? { ...p, lifecycle: response.lifecycle }
              : p,
          ),
          inFlight: 'idle',
        }
      })
      return response
    } catch (err) {
      const message =
        err instanceof Error ? err.message : 'Failed to record decision'
      set({ inFlight: 'idle', error: message })
      throw err
    }
  },

  refresh: async (proposalId) => {
    try {
      const out = await fetchProposal(proposalId)
      const hydrated = proposalFromOut(out)
      set((state) => ({
        currentProposal:
          state.currentProposal?.id === proposalId
            ? hydrated
            : state.currentProposal,
        iterations: state.iterations.some((p) => p.id === proposalId)
          ? state.iterations.map((p) => (p.id === proposalId ? hydrated : p))
          : [hydrated, ...state.iterations],
      }))
    } catch (err) {
      const message =
        err instanceof Error ? err.message : 'Failed to refresh proposal'
      set({ error: message })
    }
  },

  loadLatest: async (projectId) => {
    if (get().inFlight !== 'idle') return
    const current = get().currentProposal
    // Ya hay una propuesta cargada de ESTE proyecto (y no rechazada): no
    // pisarla. Una de otro proyecto o una rechazada sí se reemplaza.
    if (
      current &&
      current.id != null &&
      current.project_id === projectId &&
      current.lifecycle !== 'rejected'
    ) {
      return
    }
    try {
      const [out, history] = await Promise.all([
        getLatestProposal(projectId),
        getProposalHistory(projectId).catch(() => []),
      ])
      if (get().inFlight !== 'idle') return
      const hydratedHistory = history.map(proposalFromOut)
      // El historial también contiene propuestas rechazadas. No puede ocupar
      // `currentProposal`: al regresar de requerimientos el endpoint latest
      // devuelve null justamente para abrir una nueva generación, mientras
      // que tomar history[0] dejaba visible el texto rechazado y ocultaba el
      // botón "Generar propuesta".
      const hydrated = out ? proposalFromOut(out) : null
      set({
        currentProposal: hydrated,
        pendingProposal: null,
        iterations: hydratedHistory.length > 0 ? hydratedHistory : (hydrated ? [hydrated] : []),
        error: null,
      })
    } catch {
      // Silencioso: si falla, la tarjeta queda con el botón "Generar propuesta".
    }
  },

  reset: () => {
    set({
      currentProposal: null,
      pendingProposal: null,
      iterations: [],
      inFlight: 'idle',
      error: null,
    })
  },

  clearError: () => set({ error: null }),
}))
