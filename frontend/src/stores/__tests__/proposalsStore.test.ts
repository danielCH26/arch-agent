import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../../api/proposals', () => ({
  createProposalStream: vi.fn(),
  decideProposal: vi.fn(),
  getLatestProposal: vi.fn(),
  getProjectProposalState: vi.fn(),
  getProposal: vi.fn(),
}))

import * as api from '../../api/proposals'
import { proposalsStore } from '../proposalsStore'

type Callbacks = Parameters<typeof api.createProposalStream>[2]

const PROJECT_ID = 1

const progress = {
  stage: 'retrieval' as const,
  percent: 12,
  message: 'Buscando patrones de arquitectura relevantes',
  elapsed_ms: 800,
  budget_s: 300,
}

function out(id: number, iteration: number) {
  return {
    id,
    project_id: PROJECT_ID,
    iteration,
    content: `## Componentes\n- v${iteration}`,
    citations: [],
    feedback: null,
    lifecycle: 'proposed' as const,
    created_at: '2026-10-01T00:00:00',
  }
}

let streams: Callbacks[] = []
let aborts: ReturnType<typeof vi.fn>[] = []

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  streams = []
  aborts = []
  proposalsStore.getState().reset()
  vi.mocked(api.createProposalStream).mockImplementation((_mode, _payload, callbacks) => {
    streams.push(callbacks)
    const abort = vi.fn()
    aborts.push(abort)
    return abort
  })
  vi.mocked(api.getProjectProposalState).mockResolvedValue({
    approved: false,
    approved_at: null,
    approval_id: null,
    proposal_snapshot_chars: 0,
    last_decision: null,
  })
  vi.mocked(api.getProposal).mockImplementation(async (id: number) => out(id, 1))
})

afterEach(() => {
  // Cierra los streams que quedaron abiertos: el store los rastrea por proyecto
  // a nivel de módulo y uno abierto haría esperar al load() del test siguiente.
  for (const callbacks of streams) callbacks.onError('cierre del test')
  proposalsStore.getState().reset()
})

/** Deja una propuesta vigente (id 5) como si se hubiera generado antes. */
function withCurrentProposal() {
  proposalsStore.getState().generate(PROJECT_ID)
  streams[0].onToken('v1')
  streams[0].onDone(5, [])
}

describe('proposalsStore progreso y cancelación (F19)', () => {
  it('guarda el progreso y el instante de inicio mientras genera, y los limpia al terminar', () => {
    proposalsStore.getState().generate(PROJECT_ID)
    expect(proposalsStore.getState().startedAt).not.toBeNull()

    streams[0].onProgress?.(progress)
    expect(proposalsStore.getState().progress).toEqual(progress)

    streams[0].onDone(9, [])
    const state = proposalsStore.getState()
    expect(state.activity).toBe('idle')
    expect(state.progress).toBeNull()
    expect(state.startedAt).toBeNull()
  })

  it('un error limpia el progreso pero conserva el mensaje', () => {
    proposalsStore.getState().generate(PROJECT_ID)
    streams[0].onProgress?.(progress)
    streams[0].onError('Se agotó el tiempo máximo')

    const state = proposalsStore.getState()
    expect(state.error).toBe('Se agotó el tiempo máximo')
    expect(state.progress).toBeNull()
    expect(state.startedAt).toBeNull()
  })

  it('cancel() aborta el stream y deja la tarjeta lista para volver a generar', () => {
    proposalsStore.getState().generate(PROJECT_ID)
    streams[0].onToken('borrador parcial')

    proposalsStore.getState().cancel()

    const state = proposalsStore.getState()
    expect(aborts[0]).toHaveBeenCalledTimes(1)
    expect(state.activity).toBe('idle')
    expect(state.cancelled).toBe(true)
    expect(state.error).toBeNull()
    expect(state.current).toBeNull()
  })

  it('después de cancelar, los eventos tardíos del stream no tocan el estado', () => {
    proposalsStore.getState().generate(PROJECT_ID)
    proposalsStore.getState().cancel()

    streams[0].onToken('tarde')
    streams[0].onProgress?.(progress)
    streams[0].onError('tarde')

    const state = proposalsStore.getState()
    expect(state.current).toBeNull()
    expect(state.progress).toBeNull()
    expect(state.error).toBeNull()
  })

  it('cancelar una modificación conserva la versión vigente', () => {
    withCurrentProposal()
    proposalsStore.getState().modify(5, 'agrega caché')
    streams[1].onToken('nueva versión a medias')

    proposalsStore.getState().cancel()

    const state = proposalsStore.getState()
    expect(aborts[1]).toHaveBeenCalledTimes(1)
    expect(state.current?.id).toBe(5)
    expect(state.current?.content).not.toContain('a medias')
    expect(state.cancelled).toBe(true)
  })

  it('cancel() sin generación en curso no hace nada', () => {
    proposalsStore.getState().cancel()
    expect(proposalsStore.getState().cancelled).toBe(false)
  })

  it('una nueva generación borra la marca de cancelado', () => {
    proposalsStore.getState().generate(PROJECT_ID)
    proposalsStore.getState().cancel()
    proposalsStore.getState().generate(PROJECT_ID)
    expect(proposalsStore.getState().cancelled).toBe(false)
  })

  it('cancelar libera la espera de load() para ese proyecto', async () => {
    proposalsStore.getState().generate(PROJECT_ID)
    proposalsStore.getState().cancel()

    // Si el abort no liberara backgroundStreams, load() quedaría colgado.
    await proposalsStore.getState().load(PROJECT_ID)
    expect(proposalsStore.getState().activity).toBe('idle')
  })

  it('lanzar otra generación mientras hay un stream vivo ABORTA el anterior', () => {
    proposalsStore.getState().generate(PROJECT_ID)
    proposalsStore.getState().generate(PROJECT_ID)

    // Sin esto el fetch anterior seguía abierto y el backend gastando tokens.
    expect(aborts[0]).toHaveBeenCalledTimes(1)
    expect(aborts[1]).not.toHaveBeenCalled()
  })

  it('los eventos tardíos del stream reemplazado no tocan la nueva generación', () => {
    proposalsStore.getState().generate(PROJECT_ID)
    proposalsStore.getState().generate(PROJECT_ID)
    streams[0].onToken('texto del stream viejo')
    streams[0].onDone(99, [])

    const state = proposalsStore.getState()
    expect(state.current?.content).toBe('')
    expect(state.activity).toBe('generating')
    expect(state.iterations).toEqual([])
  })

  it('decidir limpia la marca de cancelado (no queda "Modificación cancelada" tras aprobar)', async () => {
    vi.mocked(api.decideProposal).mockResolvedValue({
      proposal_id: 5,
      lifecycle: 'approved',
      current_phase: null,
      phase_ready: true,
    })
    withCurrentProposal()
    proposalsStore.setState({ cancelled: true })

    await proposalsStore.getState().decide(5, 'approve')

    expect(proposalsStore.getState().cancelled).toBe(false)
    expect(proposalsStore.getState().current?.lifecycle).toBe('approved')
  })

  it('reset() NO aborta el stream: termina en segundo plano y se recuerda', () => {
    proposalsStore.getState().generate(PROJECT_ID)
    proposalsStore.getState().reset()

    expect(aborts[0]).not.toHaveBeenCalled()
    streams[0].onDone(11, [])
    expect(localStorage.getItem(`archagent:user:anon:last-proposal:${PROJECT_ID}`)).toBe('11')
  })
})

describe('proposalsStore reintento de una modificación (F19)', () => {
  it('un error a mitad de la redacción descarta el borrador parcial para poder reintentar', () => {
    proposalsStore.getState().generate(PROJECT_ID)
    streams[0].onToken('## Componentes\n- API ')

    streams[0].onError('La generación superó el tiempo máximo (5 min)')

    const state = proposalsStore.getState()
    expect(state.current).toBeNull()
    expect(state.error).toContain('tiempo máximo')
    expect(state.activity).toBe('idle')
  })

  it('guarda el feedback mientras modifica y lo conserva si falla (tope de tiempo)', () => {
    withCurrentProposal()
    proposalsStore.getState().modify(5, 'agrega caché')
    expect(proposalsStore.getState().lastModify).toEqual({ proposalId: 5, feedback: 'agrega caché' })

    streams[1].onError('La generación superó el tiempo máximo (5 min)')

    const state = proposalsStore.getState()
    expect(state.lastModify).toEqual({ proposalId: 5, feedback: 'agrega caché' })
    expect(state.current?.id).toBe(5) // la versión vigente no se toca
    expect(state.error).toContain('tiempo máximo')
  })

  it('retry() vuelve a lanzar la modificación con el mismo feedback', () => {
    withCurrentProposal()
    proposalsStore.getState().modify(5, 'agrega caché')
    streams[1].onError('boom')
    vi.mocked(api.createProposalStream).mockClear()

    proposalsStore.getState().retry()

    expect(api.createProposalStream).toHaveBeenCalledTimes(1)
    expect(vi.mocked(api.createProposalStream).mock.calls[0][0]).toBe('modify')
    expect(vi.mocked(api.createProposalStream).mock.calls[0][1]).toMatchObject({
      proposalId: 5,
      feedback: 'agrega caché',
    })
    const state = proposalsStore.getState()
    expect(state.activity).toBe('modifying')
    expect(state.error).toBeNull()
  })

  it('cancelar una modificación también permite reintentarla', () => {
    withCurrentProposal()
    proposalsStore.getState().modify(5, 'agrega caché')

    proposalsStore.getState().cancel()

    expect(proposalsStore.getState().lastModify).toEqual({ proposalId: 5, feedback: 'agrega caché' })
  })

  it('al terminar bien o al generar de nuevo se olvida el feedback pendiente', () => {
    withCurrentProposal()
    proposalsStore.getState().modify(5, 'agrega caché')
    streams[1].onDone(6, [])
    expect(proposalsStore.getState().lastModify).toBeNull()

    proposalsStore.getState().modify(6, 'otro cambio')
    streams[2].onError('boom')
    expect(proposalsStore.getState().lastModify).not.toBeNull()
    proposalsStore.getState().generate(PROJECT_ID)
    expect(proposalsStore.getState().lastModify).toBeNull()
  })

  it('retry() sin nada que reintentar, o con una generación en curso, no hace nada', () => {
    proposalsStore.getState().retry()
    expect(api.createProposalStream).not.toHaveBeenCalled()

    withCurrentProposal()
    proposalsStore.getState().modify(5, 'x')
    vi.mocked(api.createProposalStream).mockClear()
    proposalsStore.getState().retry() // sigue en curso
    expect(api.createProposalStream).not.toHaveBeenCalled()
  })
})

describe('proposalsStore corte por tiempo al guardar (F19)', () => {
  it('rehidrata la última propuesta viva y conserva el error', async () => {
    vi.mocked(api.getLatestProposal).mockResolvedValue(out(12, 1))
    proposalsStore.getState().generate(PROJECT_ID)
    streams[0].onProgress?.({ ...progress, stage: 'saving', percent: 95 })

    streams[0].onError('La generación superó el tiempo máximo (5 min)')

    await vi.waitFor(() => expect(proposalsStore.getState().current?.id).toBe(12))
    expect(api.getLatestProposal).toHaveBeenCalledWith(PROJECT_ID)
    expect(proposalsStore.getState().error).toContain('tiempo máximo')
    expect(localStorage.getItem(`archagent:user:anon:last-proposal:${PROJECT_ID}`)).toBe('12')
  })

  it('un corte por tiempo antes de guardar no rehidrata', () => {
    proposalsStore.getState().generate(PROJECT_ID)
    streams[0].onProgress?.(progress)

    streams[0].onError('La generación superó el tiempo máximo (5 min)')

    expect(api.getLatestProposal).not.toHaveBeenCalled()
    expect(proposalsStore.getState().current).toBeNull()
  })
})

describe('proposalsStore: timeout durante el guardado al modificar (review PR)', () => {
  it('no deja "Reintentar" disponible y conserva el mensaje aunque la rehidratación termine', async () => {
    withCurrentProposal()
    vi.mocked(api.getLatestProposal).mockResolvedValue(out(6, 2))
    proposalsStore.getState().modify(5, 'agrega caché')
    streams[1].onProgress?.({ ...progress, stage: 'saving', percent: 95 })

    streams[1].onError('La generación superó el tiempo máximo (5 min)')

    expect(proposalsStore.getState().lastModify).toBeNull()
    await vi.waitFor(() => expect(proposalsStore.getState().current?.id).toBe(6))
    expect(proposalsStore.getState().error).toContain('tiempo máximo')
  })

  it('si la rehidratación falla en silencio tampoco se ofrece reintentar', async () => {
    withCurrentProposal()
    vi.mocked(api.getLatestProposal).mockRejectedValue(new Error('red caída'))
    proposalsStore.getState().modify(5, 'agrega caché')
    streams[1].onProgress?.({ ...progress, stage: 'saving', percent: 95 })

    streams[1].onError('La generación superó el tiempo máximo (5 min)')
    await Promise.resolve()

    const state = proposalsStore.getState()
    expect(state.lastModify).toBeNull()
    expect(state.current?.id).toBe(5)
    expect(state.error).toContain('tiempo máximo')
  })

  it('un timeout que NO fue guardando sigue permitiendo reintentar', () => {
    withCurrentProposal()
    proposalsStore.getState().modify(5, 'agrega caché')
    streams[1].onProgress?.(progress)

    streams[1].onError('La generación superó el tiempo máximo (5 min)')

    expect(proposalsStore.getState().lastModify).toEqual({ proposalId: 5, feedback: 'agrega caché' })
    expect(api.getLatestProposal).not.toHaveBeenCalled()
  })
})
