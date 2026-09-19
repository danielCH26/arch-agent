import { create } from 'zustand'
import {
  type ProposalCitation,
  type ProposalDecision,
  type ProposalDecisionResponse,
  type ProposalOut,
  createProposalStream,
  decideProposal,
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
  iterations: [],
  inFlight: 'idle',
  error: null,

  generate: async (projectId: number) => {
    set({
      inFlight: 'generating',
      error: null,
      currentProposal: emptyProposal(projectId),
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
        onDone: (proposalId, citations) => {
          set((state) => {
            const base = state.currentProposal ?? emptyProposal(projectId)
            const finalized: Proposal = {
              ...base,
              id: proposalId,
              citations,
              // lifecycle stays 'proposed' until the user clicks Aprobar/Rechazar.
            }
            return {
              currentProposal: finalized,
              iterations: [finalized, ...state.iterations],
              inFlight: 'idle',
            }
          })
        },
        onError: (message) => {
          set({ inFlight: 'idle', error: message })
        },
      },
    )
  },

  modify: async (proposalId: number, feedback: string) => {
    // Snapshot the prior iteration so we can hydrate UI instantly while the
    // new stream starts. The new iteration replaces currentProposal on done.
    const prior = get().iterations.find((p) => p.id === proposalId)
    set({
      inFlight: 'modifying',
      error: null,
      currentProposal: prior
        ? {
            ...emptyProposal(prior.project_id),
            iteration: prior.iteration, // updated on done
          }
        : emptyProposal(0),
    })

    createProposalStream(
      'modify',
      { project_id: prior?.project_id ?? 0, feedback, proposal_id: proposalId },
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
        onDone: (newProposalId, citations) => {
          set((state) => {
            const base = state.currentProposal ?? emptyProposal(0)
            const finalized: Proposal = {
              ...base,
              id: newProposalId,
              citations,
              feedback,
              iteration: (prior?.iteration ?? 0) + 1,
            }
            return {
              currentProposal: finalized,
              iterations: [finalized, ...state.iterations],
              inFlight: 'idle',
            }
          })
        },
        onError: (message) => {
          set({ inFlight: 'idle', error: message })
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

  reset: () => {
    set({
      currentProposal: null,
      iterations: [],
      inFlight: 'idle',
      error: null,
    })
  },

  clearError: () => set({ error: null }),
}))