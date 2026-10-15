import { create } from 'zustand'
import { ApiError } from '../api/client'
import { authStore } from './authStore'
import { useApprovalsStore } from './approvalsStore'
import { projectsStore } from './projectsStore'
import {
  createProposalStream,
  decideProposal,
  getLatestProposal,
  getProjectProposalState,
  getProposal,
  type ProjectProposalState,
  type ProposalCitation,
  type ProposalDecision,
  type ProposalDecisionResponse,
  type ProposalErrorInfo,
  type ProposalLifecycle,
  type ProposalOut,
  type ProposalProgress,
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
  /**
   * El backend marcó el último error como reintentable (`retryable` del evento
   * SSE `error`). Solo tiene sentido si `error !== null`; se fija SIEMPRE junto
   * con `error`, nunca se deduce del texto del mensaje.
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
   * El formulario ya se cerró y su texto se borró: se guarda aquí para poder
   * reintentarla sin que el usuario reescriba el feedback.
   */
  lastModify: { proposalId: number; feedback: string } | null
  load: (projectId: number) => Promise<void>
  generate: (projectId: number) => void
  modify: (proposalId: number, feedback: string) => void
  /** Aborta la generación/modificación en curso sin guardar nada (F19). */
  cancel: () => void
  /** Reintenta la última modificación que no terminó, con el mismo feedback. */
  retry: () => void
  decide: (proposalId: number, decision: ProposalDecision, comment?: string) => Promise<ProposalDecisionResponse>
  refresh: (proposalId: number) => Promise<void>
  reset: () => void
}

// El backend no expone un listado de propuestas por proyecto, así que se
// recuerda en el navegador la última propuesta generada para rehidratarla al
// recargar. La clave incluye el usuario y se borra al cerrar sesión (prefijo
// `archagent:user:`, ver authStore). En otro navegador no hay forma de
// recuperarla hasta que el backend ofrezca ese listado.
const lastProposalKey = (projectId: number) =>
  `archagent:user:${authStore.getState().user?.id ?? 'anon'}:last-proposal:${projectId}`
// Clave usada antes del cambio de marca; se migra al leerla.
const legacyProposalKey = (projectId: number) => `arqagent:last-proposal:${projectId}`

function rememberProposal(projectId: number, proposalId: number) {
  try { localStorage.setItem(lastProposalKey(projectId), String(proposalId)) } catch { /* sin storage */ }
}

function recalledProposal(projectId: number): number | null {
  try {
    const legacy = localStorage.getItem(legacyProposalKey(projectId))
    if (legacy !== null) {
      localStorage.removeItem(legacyProposalKey(projectId))
      if (localStorage.getItem(lastProposalKey(projectId)) === null) {
        localStorage.setItem(lastProposalKey(projectId), legacy)
      }
    }
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

// Stream en curso que se puede abortar con "Cancelar" (F19). `settle` libera
// la espera de load() (backgroundStreams): un abort es silencioso y no llega a
// onDone/onError, así que sin esto load() quedaría esperando para siempre.
let activeAbort: { streamId: number; abort: () => void; settle: () => void } | null = null
// Versión vigente mientras se genera una modificación: "Cancelar" vuelve a ella.
let modifyBase: Proposal | null = null

function abortActiveStream() {
  const active = activeAbort
  activeAbort = null
  if (!active) return
  active.abort()
  active.settle()
}

const IDLE_PROGRESS = { progress: null, startedAt: null } as const

interface FailureDetails {
  /** Código HTTP cuando el error viene de la respuesta (p. ej. 409). */
  status?: number
  /** El tope se agotó guardando (`code=save_timeout`): la fila pudo quedar escrita. */
  savingTimedOut: boolean
}

// Streams que siguen corriendo aunque la tarjeta se haya desmontado (reset()
// solo deja de reflejarlos en pantalla). Al volver al proyecto, load() espera
// a que terminen antes de rehidratar, en vez de ofrecer generar de nuevo.
const backgroundStreams = new Map<number, Promise<void>>()

function trackStream(projectId: number) {
  let settle = () => {}
  const pending = new Promise<void>((resolve) => { settle = resolve })
  backgroundStreams.set(projectId, pending)
  return () => {
    if (backgroundStreams.get(projectId) === pending) backgroundStreams.delete(projectId)
    settle()
  }
}

export const proposalsStore = create<ProposalsState>((set, get) => {
  const streamHandlers = (
    streamId: number,
    projectId: number,
    onFailure: (error: string, details: FailureDetails) => void,
  ) => {
    const settle = trackStream(projectId)
    const release = () => {
      if (activeAbort?.streamId === streamId) activeAbort = null
      settle()
    }
    const handlers = {
      onProgress: (progress: ProposalProgress) => {
        if (streamId !== activeStream) return
        set({ progress })
      },
      onSources: (citations: ProposalCitation[]) => {
        if (streamId !== activeStream) return
        set((state) => state.current ? { current: { ...state.current, citations } } : {})
      },
      onToken: (token: string) => {
        if (streamId !== activeStream) return
        set((state) => state.current ? { current: { ...state.current, content: state.current.content + token } } : {})
      },
      onDone: (id: number, citations: ProposalCitation[]) => {
        // Se recuerda aunque el usuario haya salido: la propuesta ya existe en
        // el servidor y regenerarla gastaría otra iteración.
        rememberProposal(projectId, id)
        release()
        if (streamId !== activeStream) return
        set((state) => {
          if (!state.current) return { activity: 'idle', lastModify: null, ...IDLE_PROGRESS }
          const proposal = { ...state.current, id, citations }
          return { current: proposal, iterations: [proposal, ...state.iterations], activity: 'idle', lastModify: null, ...IDLE_PROGRESS }
        })
        // El backend guarda la iteración definitiva; sincronizamos número y contenido.
        void get().refresh(id)
      },
      onError: (error: string, status?: number, info?: ProposalErrorInfo) => {
        release()
        if (streamId !== activeStream) return
        // El tope se agotó guardando: la fila pudo quedar escrita (código
        // estructurado del backend, no el texto del mensaje).
        const savingTimedOut = info?.code === 'save_timeout'
        set({ ...IDLE_PROGRESS, errorRetryable: info?.retryable === true })
        onFailure(error, { status, savingTimedOut })
      },
    }
    // Se registra antes de abrir el stream; createProposalStream devuelve el
    // abort y se adjunta con `track`.
    const track = (abort: () => void) => {
      // El stream pudo terminar de forma síncrona (tests) antes de devolver el abort.
      const { activity } = get()
      const live = activity === 'generating' || activity === 'modifying'
      if (streamId === activeStream && live && typeof abort === 'function') {
        activeAbort = { streamId, abort, settle }
      }
    }
    return { handlers, track }
  }

  // Tras un corte por tiempo GUARDANDO, la fila pudo quedar escrita: se trae la
  // última propuesta viva del backend y se adopta como vigente. El mensaje de
  // error se conserva: es lo que explica por qué el usuario no vio el final.
  const rehydrateLatest = async (streamId: number, projectId: number) => {
    try {
      const latest = await getLatestProposal(projectId)
      if (streamId !== activeStream || !latest || latest.project_id !== projectId) return
      rememberProposal(projectId, latest.id)
      const proposal = fromOut(latest)
      set((state) => ({
        current: proposal,
        iterations: [proposal, ...state.iterations.filter((item) => item.id !== proposal.id)],
      }))
    } catch {
      // Silencioso: si falla, la tarjeta queda con el error y el botón de reintento.
    }
  }

  return {
    current: null,
    iterations: [],
    projectState: null,
    activity: 'idle',
    error: null,
    errorRetryable: false,
    progress: null,
    startedAt: null,
    cancelled: false,
    lastModify: null,

    load: async (projectId) => {
      const streamId = ++activeStream
      const pending = backgroundStreams.get(projectId)
      if (pending) {
        // Una generación de este proyecto sigue en curso tras salir de la
        // página: se muestra como tal y se recarga cuando termine.
        set({ current: null, iterations: [], projectState: null, activity: 'generating', error: null, errorRetryable: false })
        await pending
        if (streamId !== activeStream) return
      }
      set({ current: null, iterations: [], projectState: null, activity: 'loading', error: null, errorRetryable: false, cancelled: false, ...IDLE_PROGRESS })
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
      // Un stream anterior todavía vivo se aborta: si no, el backend seguiría
      // gastando tokens en una propuesta que nadie va a ver.
      abortActiveStream()
      const streamId = ++activeStream
      set({
        current: newProposal(projectId),
        iterations: [],
        activity: 'generating',
        error: null,
        errorRetryable: false,
        cancelled: false,
        lastModify: null,
        progress: null,
        startedAt: Date.now(),
      })
      const { handlers, track } = streamHandlers(streamId, projectId, (error, { status, savingTimedOut }) => {
        set({ current: null, activity: 'idle', error })
        // El hilo de persistencia puede completar justo después del timeout:
        // se rehidrata para no ofrecer un reintento que chocará con la
        // iteración que ya alcanzó a guardarse.
        if (savingTimedOut) void rehydrateLatest(streamId, projectId)
        // 409: el estado cambió en el backend (p. ej. la propuesta ya se aprobó
        // en otra pestaña); se vuelve a cargar sin perder el mensaje de error.
        if (status === 409) {
          void get().load(projectId).then(() => set({ error }))
        }
      })
      track(createProposalStream('generate', { projectId }, handlers))
    },

    modify: (proposalId, feedback) => {
      const previous = get().iterations.find((proposal) => proposal.id === proposalId) ?? get().current
      if (!previous) return
      abortActiveStream()
      const streamId = ++activeStream
      const draft: Proposal = { ...newProposal(previous.projectId), iteration: previous.iteration + 1, feedback }
      modifyBase = previous
      set({
        current: draft,
        activity: 'modifying',
        error: null,
        errorRetryable: false,
        cancelled: false,
        lastModify: { proposalId, feedback },
        progress: null,
        startedAt: Date.now(),
      })
      const { handlers, track } = streamHandlers(streamId, previous.projectId, (error, { savingTimedOut }) => {
        // Si la iteración falla, se vuelve a mostrar la propuesta anterior.
        set({
          current: previous,
          activity: 'idle',
          error,
          // Si el corte fue GUARDANDO, la iteración pudo quedar en la base: un
          // reintento con el `proposalId` viejo chocaría con un 409. Se olvida
          // el feedback pendiente y se rehidrata para que el usuario vea el
          // estado real y decida desde ahí.
          ...(savingTimedOut ? { lastModify: null } : {}),
        })
        if (savingTimedOut) void rehydrateLatest(streamId, previous.projectId)
        else void get().refresh(proposalId)
      })
      track(createProposalStream('modify', { projectId: previous.projectId, proposalId, feedback }, handlers))
    },

    cancel: () => {
      const { activity } = get()
      if (activity !== 'generating' && activity !== 'modifying') return
      // Aborta el fetch (el backend cierra el LLM) e invalida callbacks tardíos.
      abortActiveStream()
      activeStream += 1
      set({
        activity: 'idle',
        error: null,
        errorRetryable: false,
        cancelled: true,
        ...IDLE_PROGRESS,
        // Generar desde cero: el borrador parcial no se conserva y la tarjeta
        // vuelve a ofrecer "Generar propuesta". Al modificar, se vuelve a la
        // versión vigente, que nunca se tocó.
        current: activity === 'generating' ? null : modifyBase,
      })
    },

    retry: () => {
      const { lastModify, activity } = get()
      if (!lastModify || activity !== 'idle') return
      get().modify(lastModify.proposalId, lastModify.feedback)
    },

    decide: async (proposalId, decision, comment) => {
      set({ activity: 'deciding', error: null, errorRetryable: false, cancelled: false, lastModify: null })
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
        // HU10: en `propuesta` esta tarjeta y <PhaseActions> leen el MISMO
        // estado del servidor (pending decision + phase_ready + current_phase).
        // La decisión lo cambió, así que re-sincronizamos ambos stores; si no,
        // PhaseActions sigue mostrando botones pendientes y "Avanzar" nunca
        // aparece hasta un mensaje de chat o un reload. Ninguno puede hacer
        // fallar la decisión.
        void Promise.resolve(useApprovalsStore.getState().refresh()).catch(() => undefined)
        const loadedProjectId = projectsStore.getState().currentProject?.id ?? projectId
        if (loadedProjectId != null) {
          void Promise.resolve(projectsStore.getState().getProject(loadedProjectId)).catch(() => undefined)
        }
        return result
      } catch (error) {
        const message = error instanceof Error ? error.message : 'No se pudo registrar la decisión.'
        set({ activity: 'idle', error: message, errorRetryable: false })
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
      // No aborta: un stream que sigue tras desmontar la tarjeta termina en
      // segundo plano y load() lo espera (ver backgroundStreams). Solo
      // "Cancelar" corta un stream, y solo el que está en pantalla: se suelta la
      // referencia para que un generate() posterior no aborte el de fondo.
      activeAbort = null
      modifyBase = null
      activeStream += 1
      set({ current: null, iterations: [], projectState: null, activity: 'idle', error: null, errorRetryable: false, cancelled: false, lastModify: null, ...IDLE_PROGRESS })
    },
  }
})
