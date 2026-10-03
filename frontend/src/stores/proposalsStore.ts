import { create } from 'zustand'
import {
  type ProposalCitation,
  type ProposalDecision,
  type ProposalDecisionResponse,
  type ProposalOut,
  type ProposalProgress,
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
  /** Última etapa reportada por el backend (F19); null fuera de una generación. */
  progress: ProposalProgress | null
  /** Date.now() cuando arrancó la generación en curso; base del cronómetro. */
  startedAt: number | null
  /** true si el usuario canceló la última generación (mensaje neutro, no error). */
  cancelled: boolean

  // Streaming actions
  generate: (projectId: number) => Promise<void>
  modify: (proposalId: number, feedback: string) => Promise<void>
  /** Aborta la generación/modificación en curso sin guardar nada (F19). */
  cancel: () => void

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

// Stream activo (a lo sumo uno). `runId` invalida los callbacks de un stream
// cancelado o reemplazado: aunque llegue un evento tardío, no toca el estado.
let activeRun = 0
let abortActive: (() => void) | null = null

function startRun(): number {
  abortActive = null
  activeRun += 1
  return activeRun
}

function trackAbort(run: number, abort: unknown, isBusy: boolean) {
  // El stream pudo terminar de forma síncrona (tests) antes de devolver el abort.
  abortActive = run === activeRun && isBusy && typeof abort === 'function'
    ? (abort as () => void)
    : null
}

const IDLE_PROGRESS = { progress: null, startedAt: null } as const

export const proposalsStore = create<ProposalsState>((set, get) => ({
  currentProposal: null,
  pendingProposal: null,
  iterations: [],
  inFlight: 'idle',
  error: null,
  progress: null,
  startedAt: null,
  cancelled: false,

  generate: async (projectId: number) => {
    const run = startRun()
    set({
      inFlight: 'generating',
      error: null,
      cancelled: false,
      progress: null,
      startedAt: Date.now(),
      currentProposal: emptyProposal(projectId),
      pendingProposal: null,
    })

    const abort = createProposalStream(
      'generate',
      { project_id: projectId },
      {
        onProgress: (progress) => {
          if (run !== activeRun) return
          set({ progress })
        },
        onSources: (citations) => {
          if (run !== activeRun) return
          set((state) =>
            state.currentProposal
              ? { currentProposal: { ...state.currentProposal, citations } }
              : {},
          )
        },
        onToken: (token) => {
          if (run !== activeRun) return
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
          if (run !== activeRun) return
          abortActive = null
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
              ...IDLE_PROGRESS,
            }
          })
        },
        onError: (message) => {
          if (run !== activeRun) return
          abortActive = null
          set({
            inFlight: 'idle',
            error: message,
            pendingProposal: null,
            ...IDLE_PROGRESS,
          })
        },
      },
    )
    trackAbort(run, abort, get().inFlight !== 'idle')
  },

  modify: async (proposalId: number, feedback: string) => {
    // Keep the current iteration visible and immutable while the next one is
    // streamed. Replacing it with an empty draft made feedback appear to erase
    // the proposal until the request finished.
    const current = get().currentProposal
    const prior =
      get().iterations.find((p) => p.id === proposalId) ??
      (current?.id === proposalId ? current : undefined)
    const run = startRun()
    set({
      inFlight: 'modifying',
      error: null,
      cancelled: false,
      progress: null,
      startedAt: Date.now(),
      pendingProposal: emptyProposal(prior?.project_id ?? 0),
    })

    const abort = createProposalStream(
      'modify',
      { project_id: prior?.project_id ?? 0, feedback, proposal_id: proposalId },
      {
        onProgress: (progress) => {
          if (run !== activeRun) return
          set({ progress })
        },
        onSources: (citations) => {
          if (run !== activeRun) return
          set((state) =>
            state.pendingProposal
              ? { pendingProposal: { ...state.pendingProposal, citations } }
              : {},
          )
        },
        onToken: (token) => {
          if (run !== activeRun) return
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
          if (run !== activeRun) return
          abortActive = null
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
              ...IDLE_PROGRESS,
            }
          })
        },
        onError: (message) => {
          if (run !== activeRun) return
          abortActive = null
          set({
            inFlight: 'idle',
            error: message,
            pendingProposal: null,
            ...IDLE_PROGRESS,
          })
        },
      },
    )
    trackAbort(run, abort, get().inFlight !== 'idle')
  },

  cancel: () => {
    const { inFlight, currentProposal } = get()
    if (inFlight !== 'generating' && inFlight !== 'modifying') return

    // Aborta el fetch (el backend cierra el LLM) e invalida callbacks tardíos.
    const abort = abortActive
    startRun()
    abort?.()

    set({
      inFlight: 'idle',
      error: null,
      cancelled: true,
      pendingProposal: null,
      ...IDLE_PROGRESS,
      // Generar desde cero: el borrador vacío/parcial no se conserva y la
      // tarjeta vuelve a ofrecer "Generar propuesta". Al modificar, la versión
      // vigente nunca se tocó.
      currentProposal: inFlight === 'generating' ? null : currentProposal,
    })
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
      // La vigente sale de /proposals/latest (excluye rechazadas). El
      // historial incluye rechazadas, así que solo alimenta `iterations`:
      // si todas están rechazadas, `out` es null y la tarjeta ofrece
      // "Generar propuesta" en vez de mostrar una versión rechazada.
      const hydrated = out ? proposalFromOut(out) : null
      set({
        currentProposal: hydrated,
        pendingProposal: null,
        iterations:
          hydratedHistory.length > 0 ? hydratedHistory : hydrated ? [hydrated] : [],
        error: null,
      })
    } catch {
      // Silencioso: si falla, la tarjeta queda con el botón "Generar propuesta".
    }
  },

  reset: () => {
    // Si había un stream vivo (cambio de proyecto, logout), se aborta también.
    const abort = abortActive
    startRun()
    abort?.()
    set({
      currentProposal: null,
      pendingProposal: null,
      iterations: [],
      inFlight: 'idle',
      error: null,
      cancelled: false,
      ...IDLE_PROGRESS,
    })
  },

  clearError: () => set({ error: null }),
}))
