import { create } from 'zustand'
import {
  createProposalStream,
  decideProposal,
  type ProposalCitation,
  type ProposalDecision,
  type ProposalDecisionResponse,
  type ProposalLifecycle,
} from '../api/proposals'

export interface Proposal {
  id: number | null
  projectId: number
  iteration: number
  content: string
  citations: ProposalCitation[]
  feedback: string | null
  lifecycle: ProposalLifecycle
}

type ProposalActivity = 'idle' | 'generating' | 'modifying' | 'deciding'

interface ProposalsState {
  current: Proposal | null
  iterations: Proposal[]
  activity: ProposalActivity
  error: string | null
  generate: (projectId: number) => void
  modify: (proposalId: number, feedback: string) => void
  decide: (proposalId: number, decision: ProposalDecision, comment?: string) => Promise<ProposalDecisionResponse>
  reset: () => void
}

const newProposal = (projectId: number): Proposal => ({
  id: null,
  projectId,
  iteration: 1,
  content: '',
  citations: [],
  feedback: null,
  lifecycle: 'proposed',
})

let activeStream = 0

export const proposalsStore = create<ProposalsState>((set, get) => ({
  current: null,
  iterations: [],
  activity: 'idle',
  error: null,

  generate: (projectId) => {
    const streamId = ++activeStream
    set({ current: newProposal(projectId), iterations: [], activity: 'generating', error: null })
    createProposalStream('generate', { projectId }, {
      onSources: (citations) => {
        if (streamId !== activeStream) return
        set((state) => state.current ? { current: { ...state.current, citations } } : {})
      },
      onToken: (token) => {
        if (streamId !== activeStream) return
        set((state) => state.current ? { current: { ...state.current, content: state.current.content + token } } : {})
      },
      onDone: (id, citations) => {
        if (streamId !== activeStream) return
        set((state) => {
          const proposal = state.current ? { ...state.current, id, citations } : null
          return { current: proposal, iterations: proposal ? [proposal] : [], activity: 'idle' }
        })
      },
      onError: (error) => {
        if (streamId === activeStream) set({ activity: 'idle', error })
      },
    })
  },

  modify: (proposalId, feedback) => {
    const previous = get().iterations.find((proposal) => proposal.id === proposalId) ?? get().current
    if (!previous) return
    const streamId = ++activeStream
    const draft: Proposal = { ...newProposal(previous.projectId), iteration: previous.iteration + 1, feedback }
    set({ current: draft, activity: 'modifying', error: null })
    createProposalStream('modify', { projectId: previous.projectId, proposalId, feedback }, {
      onSources: (citations) => {
        if (streamId !== activeStream) return
        set((state) => state.current ? { current: { ...state.current, citations } } : {})
      },
      onToken: (token) => {
        if (streamId !== activeStream) return
        set((state) => state.current ? { current: { ...state.current, content: state.current.content + token } } : {})
      },
      onDone: (id, citations) => {
        if (streamId !== activeStream) return
        set((state) => {
          const proposal = state.current ? { ...state.current, id, citations } : null
          return { current: proposal, iterations: proposal ? [proposal, ...state.iterations] : state.iterations, activity: 'idle' }
        })
      },
      onError: (error) => {
        if (streamId === activeStream) set({ activity: 'idle', error })
      },
    })
  },

  decide: async (proposalId, decision, comment) => {
    set({ activity: 'deciding', error: null })
    try {
      const result = await decideProposal(proposalId, decision, comment)
      set((state) => ({
        current: state.current?.id === proposalId ? { ...state.current, lifecycle: result.lifecycle } : state.current,
        iterations: state.iterations.map((proposal) => proposal.id === proposalId ? { ...proposal, lifecycle: result.lifecycle } : proposal),
        activity: 'idle',
      }))
      return result
    } catch (error) {
      const message = error instanceof Error ? error.message : 'No se pudo registrar la decisión.'
      set({ activity: 'idle', error: message })
      throw error
    }
  },

  reset: () => {
    activeStream += 1
    set({ current: null, iterations: [], activity: 'idle', error: null })
  },
}))
