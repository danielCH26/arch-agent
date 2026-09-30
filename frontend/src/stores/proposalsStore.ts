import { create } from 'zustand'
import { ApiError } from '../api/client'
import {
  createProposalStream,
  decideProposal,
  getProjectProposalState,
  getProposal,
  type ProjectProposalState,
  type ProposalCitation,
  type ProposalDecision,
  type ProposalDecisionResponse,
  type ProposalLifecycle,
  type ProposalOut,
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

type ProposalActivity = 'idle' | 'loading' | 'generating' | 'modifying' | 'deciding'

interface ProposalsState {
  current: Proposal | null
  iterations: Proposal[]
  projectState: ProjectProposalState | null
  activity: ProposalActivity
  error: string | null
  load: (projectId: number) => Promise<void>
  generate: (projectId: number) => void
  modify: (proposalId: number, feedback: string) => void
  decide: (proposalId: number, decision: ProposalDecision, comment?: string) => Promise<ProposalDecisionResponse>
  refresh: (proposalId: number) => Promise<void>
  reset: () => void
}

// El backend no expone un listado de propuestas por proyecto, así que
// recordamos la última propuesta generada para rehidratarla al recargar.
const lastProposalKey = (projectId: number) => `arqagent:last-proposal:${projectId}`

function rememberProposal(projectId: number, proposalId: number) {
  try { localStorage.setItem(lastProposalKey(projectId), String(proposalId)) } catch { /* sin storage */ }
}

function recalledProposal(projectId: number): number | null {
  try {
    const value = Number(localStorage.getItem(lastProposalKey(projectId)))
    return Number.isInteger(value) && value > 0 ? value : null
  } catch {
    return null
  }
}

function forgetProposal(projectId: number) {
  try { localStorage.removeItem(lastProposalKey(projectId)) } catch { /* sin storage */ }
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

const fromOut = (out: ProposalOut): Proposal => ({
  id: out.id,
  projectId: out.project_id,
  iteration: out.iteration,
  content: out.content,
  citations: out.citations ?? [],
  feedback: out.feedback,
  lifecycle: out.lifecycle,
})

let activeStream = 0

export const proposalsStore = create<ProposalsState>((set, get) => {
  const streamHandlers = (streamId: number, onFailure: (error: string) => void) => ({
    onSources: (citations: ProposalCitation[]) => {
      if (streamId !== activeStream) return
      set((state) => state.current ? { current: { ...state.current, citations } } : {})
    },
    onToken: (token: string) => {
      if (streamId !== activeStream) return
      set((state) => state.current ? { current: { ...state.current, content: state.current.content + token } } : {})
    },
    onDone: (id: number, citations: ProposalCitation[]) => {
      if (streamId !== activeStream) return
      set((state) => {
        if (!state.current) return { activity: 'idle' }
        const proposal = { ...state.current, id, citations }
        rememberProposal(proposal.projectId, id)
        return { current: proposal, iterations: [proposal, ...state.iterations], activity: 'idle' }
      })
      // El backend guarda la iteración definitiva; sincronizamos número y contenido.
      void get().refresh(id)
    },
    onError: (error: string) => {
      if (streamId === activeStream) onFailure(error)
    },
  })

  return {
    current: null,
    iterations: [],
    projectState: null,
    activity: 'idle',
    error: null,

    load: async (projectId) => {
      const streamId = ++activeStream
      set({ current: null, iterations: [], projectState: null, activity: 'loading', error: null })
      const proposalId = recalledProposal(projectId)
      const [proposal, projectState] = await Promise.all([
        proposalId
          ? getProposal(proposalId).catch((error) => {
              if (error instanceof ApiError && [403, 404].includes(error.status)) forgetProposal(projectId)
              return null
            })
          : Promise.resolve(null),
        getProjectProposalState(projectId).catch(() => null),
      ])
      if (streamId !== activeStream) return
      const current = proposal && proposal.project_id === projectId ? fromOut(proposal) : null
      // Una propuesta rechazada devolvió el proyecto a requerimientos: al volver
      // a la fase propuesta se empieza de cero.
      const usable = current && current.lifecycle !== 'rejected' ? current : null
      set({ current: usable, iterations: usable ? [usable] : [], projectState, activity: 'idle' })
    },

    generate: (projectId) => {
      const streamId = ++activeStream
      set({ current: newProposal(projectId), iterations: [], activity: 'generating', error: null })
      createProposalStream('generate', { projectId }, streamHandlers(streamId, (error) => {
        set({ current: null, activity: 'idle', error })
      }))
    },

    modify: (proposalId, feedback) => {
      const previous = get().iterations.find((proposal) => proposal.id === proposalId) ?? get().current
      if (!previous) return
      const streamId = ++activeStream
      const draft: Proposal = { ...newProposal(previous.projectId), iteration: previous.iteration + 1, feedback }
      set({ current: draft, activity: 'modifying', error: null })
      createProposalStream('modify', { projectId: previous.projectId, proposalId, feedback }, streamHandlers(streamId, (error) => {
        // Si la iteración falla, se vuelve a mostrar la propuesta anterior.
        set({ current: previous, activity: 'idle', error })
        void get().refresh(proposalId)
      }))
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
        const projectId = get().current?.projectId
        if (projectId) {
          if (result.lifecycle === 'rejected') forgetProposal(projectId)
          void getProjectProposalState(projectId).then((projectState) => set({ projectState })).catch(() => undefined)
        }
        return result
      } catch (error) {
        const message = error instanceof Error ? error.message : 'No se pudo registrar la decisión.'
        set({ activity: 'idle', error: message })
        // 409: la propuesta cambió de estado en otra pestaña; re-sincronizamos.
        if (error instanceof ApiError && error.status === 409) await get().refresh(proposalId)
        throw error
      }
    },

    refresh: async (proposalId) => {
      try {
        const proposal = fromOut(await getProposal(proposalId))
        set((state) => ({
          current: state.current?.id === proposalId ? proposal : state.current,
          iterations: state.iterations.map((item) => item.id === proposalId ? proposal : item),
        }))
      } catch {
        // El contenido ya está en memoria; un fallo al re-sincronizar no bloquea la UI.
      }
    },

    reset: () => {
      activeStream += 1
      set({ current: null, iterations: [], projectState: null, activity: 'idle', error: null })
    },
  }
})
