import { create } from 'zustand'
import {
  type ProposalCitation,
  type ProposalDecision,
  type ProposalDecisionResponse,
  type ProposalErrorInfo,
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
  /**
   * El backend marcó el último error como reintentable (`retryable` del evento
   * SSE `error`). Solo tiene sentido si `error !== null`; lo fijan SIEMPRE
   * `errorState()` / `onError`, nunca se deduce del texto del mensaje.
   */
  errorRetryable: boolean
  /** Última etapa reportada por el backend (F19); null fuera de una generación. */
  progress: ProposalProgress | null
  /** Date.now() cuando arrancó la generación en curso; base del cronómetro. */
  startedAt: number | null
  /** true si el usuario canceló la última generación (mensaje neutro, no error). */
  cancelled: boolean
  /**
   * Última modificación pedida que NO terminó (error, tope de tiempo o cancelada).
   * El composer ya se cerró y su texto se borró: se guarda aquí para poder
   * reintentarla sin que el usuario reescriba el feedback.
   */
  lastModify: { proposalId: number; feedback: string } | null

  // Streaming actions
  generate: (projectId: number) => Promise<void>
  modify: (proposalId: number, feedback: string) => Promise<void>
  /** Aborta la generación/modificación en curso sin guardar nada (F19). */
  cancel: () => void
  /** Reintenta la última modificación que no terminó, con el mismo feedback. */
  retry: () => Promise<void>

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
  loadLatest: (projectId: number, force?: boolean) => Promise<void>

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
// Proyecto del stream activo: lo necesita cancel() para resincronizar con el servidor.
let activeProjectId = 0

function startRun(): number {
  // Si todavía había un stream vivo se ABORTA (no solo se invalida): sin esto el
  // fetch anterior seguía abierto y el backend siguiendo gastando tokens de una
  // propuesta que nadie va a ver.
  const previous = abortActive
  abortActive = null
  activeRun += 1
  previous?.()
  return activeRun
}

function trackAbort(run: number, abort: unknown, isBusy: boolean) {
  // El stream pudo terminar de forma síncrona (tests) antes de devolver el abort.
  abortActive = run === activeRun && isBusy && typeof abort === 'function'
    ? (abort as () => void)
    : null
}

const IDLE_PROGRESS = { progress: null, startedAt: null } as const

/** Fija `error` y su flag de reintento a la vez: no pueden quedar desfasados. */
function errorState(message: string, info?: ProposalErrorInfo) {
  return { error: message, errorRetryable: info?.retryable === true }
}

/** El tope se agotó guardando: la fila pudo quedar escrita (código estructurado). */
function isSaveTimeout(info?: ProposalErrorInfo): boolean {
  return info?.code === 'save_timeout'
}

export const proposalsStore = create<ProposalsState>((set, get) => ({
  currentProposal: null,
  pendingProposal: null,
  iterations: [],
  inFlight: 'idle',
  error: null,
  errorRetryable: false,
  progress: null,
  startedAt: null,
  cancelled: false,
  lastModify: null,

  generate: async (projectId: number) => {
    const run = startRun()
    activeProjectId = projectId
    set({
      inFlight: 'generating',
      error: null,
      cancelled: false,
      lastModify: null,
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
        onError: (message, info) => {
          if (run !== activeRun) return
          const savingTimedOut = isSaveTimeout(info)
          abortActive = null
          set({
            inFlight: 'idle',
            ...errorState(message, info),
            pendingProposal: null,
            // El borrador a medias (p. ej. cortado por el tope de tiempo) no es
            // una propuesta válida: se descarta para que la tarjeta muestre el
            // error y vuelva a ofrecer "Generar propuesta".
            currentProposal: null,
            ...IDLE_PROGRESS,
          })
          // El hilo de persistencia puede completar justo después del timeout.
          // Forzamos la rehidratación para no ofrecer un reintento que chocará
          // con la iteración que ya alcanzó a guardarse.
          if (savingTimedOut) void get().loadLatest(projectId, true)
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
    activeProjectId = prior?.project_id ?? 0
    set({
      inFlight: 'modifying',
      error: null,
      cancelled: false,
      lastModify: { proposalId, feedback },
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
              lastModify: null,
              ...IDLE_PROGRESS,
            }
          })
        },
        onError: (message, info) => {
          if (run !== activeRun) return
          const savingTimedOut = isSaveTimeout(info)
          abortActive = null
          set({
            inFlight: 'idle',
            ...errorState(message, info),
            pendingProposal: null,
            ...IDLE_PROGRESS,
            // Si el corte fue GUARDANDO, la iteración pudo quedar en la base: un
            // reintento con el `proposalId` viejo chocaría con un 409. Se
            // olvida el feedback pendiente y se rehidrata (abajo) para que el
            // usuario vea el estado real y decida desde ahí.
            ...(savingTimedOut ? { lastModify: null } : {}),
          })
          if (savingTimedOut) {
            const projectId = prior?.project_id ?? 0
            if (projectId) void get().loadLatest(projectId, true)
          }
        },
      },
    )
    trackAbort(run, abort, get().inFlight !== 'idle')
  },

  retry: async () => {
    const { lastModify, inFlight } = get()
    if (!lastModify || inFlight !== 'idle') return
    await get().modify(lastModify.proposalId, lastModify.feedback)
  },

  cancel: () => {
    const { inFlight, currentProposal } = get()
    if (inFlight !== 'generating' && inFlight !== 'modifying') return

    // Aborta el fetch (el backend cierra el LLM) e invalida callbacks tardíos.
    const run = startRun()
    const projectId = activeProjectId
    // Id de la versión vigente ANTES de cancelar (undefined al generar desde cero).
    const priorId = inFlight === 'modifying' ? currentProposal?.id : undefined

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

    // "Cancelar" solo deja de esperar: si el servidor ya estaba guardando cuando
    // el usuario pulsó (el botón desaparece cuando LLEGA `saving`, no cuando
    // empieza), la iteración puede haberse confirmado igual. El backend intenta
    // evitarlo (cancel_event antes del commit), pero aquí se resincroniza siempre
    // con la BD, igual que en el timeout de `saving`, para no mostrar un estado
    // distinto del real (p. ej. "Generar propuesta" con una iteración ya gastada).
    if (projectId) {
      void get()
        .loadLatest(projectId, true)
        .then(() => {
          if (run !== activeRun) return
          const s = get()
          const savedAnyway =
            s.currentProposal?.id != null && s.currentProposal.id !== priorId
          // La cancelación llegó tarde: no afirmar "cancelada" si se guardó algo nuevo.
          if (s.cancelled && s.inFlight === 'idle' && savedAnyway) set({ cancelled: false })
        })
    }
  },

  decide: async (proposalId, decision, comment) => {
    set({ inFlight: 'deciding', error: null, cancelled: false, lastModify: null })
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
      set({ inFlight: 'idle', ...errorState(message) })
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
      set(errorState(message))
    }
  },

  loadLatest: async (projectId, force = false) => {
    if (get().inFlight !== 'idle') return
    const current = get().currentProposal
    // Ya hay una propuesta cargada de ESTE proyecto (y no rechazada): no
    // pisarla. Una de otro proyecto o una rechazada sí se reemplaza.
    if (
      !force &&
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
        // La rehidratación forzada ocurre justo tras un corte por tiempo al
        // guardar: el mensaje de error es lo único que le explica al usuario
        // por qué no ve su propuesta, así que no se borra.
        ...(force ? {} : { error: null }),
      })
    } catch {
      // Silencioso: si falla, la tarjeta queda con el botón "Generar propuesta".
    }
  },

  reset: () => {
    // Si había un stream vivo (cambio de proyecto, logout), se aborta también.
    startRun()
    set({
      currentProposal: null,
      pendingProposal: null,
      iterations: [],
      inFlight: 'idle',
      error: null,
      errorRetryable: false,
      cancelled: false,
      lastModify: null,
      ...IDLE_PROGRESS,
    })
  },

  clearError: () => set({ error: null }),
}))
