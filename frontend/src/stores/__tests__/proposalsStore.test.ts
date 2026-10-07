import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('../../api/proposals', () => ({
  createProposalStream: vi.fn(),
  decideProposal: vi.fn(),
  getProposal: vi.fn(),
  getLatestProposal: vi.fn(),
  getProposalHistory: vi.fn(),
}))

import * as api from '../../api/proposals'
import { proposalsStore } from '../proposalsStore'

type Lifecycle = 'proposed' | 'approved' | 'rejected'

function out(id: number, iteration: number, lifecycle: Lifecycle) {
  return {
    id,
    project_id: 1,
    iteration,
    content: `## Componentes\n- v${iteration}`,
    citations: [],
    feedback: null,
    lifecycle,
    created_at: '2026-10-01T00:00:00',
  }
}

describe('proposalsStore.loadLatest', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    proposalsStore.getState().reset()
  })

  it('usa /proposals/latest como propuesta vigente aunque la iteración más nueva esté rechazada', async () => {
    // Historial de más reciente a más antigua: la iteración 2 fue rechazada.
    vi.mocked(api.getProposalHistory).mockResolvedValue([
      out(2, 2, 'rejected'),
      out(1, 1, 'proposed'),
    ])
    vi.mocked(api.getLatestProposal).mockResolvedValue(out(1, 1, 'proposed'))

    await proposalsStore.getState().loadLatest(1)

    const state = proposalsStore.getState()
    expect(state.currentProposal?.id).toBe(1)
    expect(state.currentProposal?.lifecycle).toBe('proposed')
    // El historial solo alimenta las iteraciones (incluye la rechazada).
    expect(state.iterations.map((p) => p.id)).toEqual([2, 1])
  })

  it('no muestra una propuesta rechazada cuando no hay ninguna viva', async () => {
    vi.mocked(api.getProposalHistory).mockResolvedValue([out(2, 2, 'rejected')])
    vi.mocked(api.getLatestProposal).mockResolvedValue(null)

    await proposalsStore.getState().loadLatest(1)

    const state = proposalsStore.getState()
    // currentProposal null => la tarjeta ofrece "Generar propuesta".
    expect(state.currentProposal).toBeNull()
    expect(state.iterations.map((p) => p.id)).toEqual([2])
  })

  it('recargar de nuevo no vuelve a caer en la versión rechazada', async () => {
    vi.mocked(api.getProposalHistory).mockResolvedValue([
      out(2, 2, 'rejected'),
      out(1, 1, 'proposed'),
    ])
    vi.mocked(api.getLatestProposal).mockResolvedValue(out(1, 1, 'proposed'))

    await proposalsStore.getState().loadLatest(1)
    proposalsStore.getState().reset()
    await proposalsStore.getState().loadLatest(1)

    expect(proposalsStore.getState().currentProposal?.id).toBe(1)
  })

  it('si el historial falla, usa la propuesta de /latest', async () => {
    vi.mocked(api.getProposalHistory).mockRejectedValue(new Error('boom'))
    vi.mocked(api.getLatestProposal).mockResolvedValue(out(3, 1, 'approved'))

    await proposalsStore.getState().loadLatest(1)

    const state = proposalsStore.getState()
    expect(state.currentProposal?.id).toBe(3)
    expect(state.iterations.map((p) => p.id)).toEqual([3])
  })
})

// --- F19: progreso y cancelación --------------------------------------------

type StreamCallbacks = Parameters<typeof api.createProposalStream>[2]

function captureStream() {
  const abort = vi.fn()
  let callbacks!: StreamCallbacks
  vi.mocked(api.createProposalStream).mockImplementation((_endpoint, _payload, cb) => {
    callbacks = cb
    return abort
  })
  return { abort, cb: () => callbacks }
}

const PROGRESS = {
  stage: 'generating' as const,
  percent: 40,
  message: 'Redactando la propuesta',
  elapsed_ms: 20_000,
  budget_s: 300,
}

describe('proposalsStore progreso y cancelación (F19)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    proposalsStore.getState().reset()
    // clearAllMocks no borra implementaciones de tests anteriores: cancel() ahora
    // resincroniza con /proposals/latest, así que el default es "no hay nada guardado".
    vi.mocked(api.getLatestProposal).mockResolvedValue(null)
    vi.mocked(api.getProposalHistory).mockResolvedValue([])
  })

  it('guarda el progreso y el instante de inicio mientras genera, y los limpia al terminar', async () => {
    const { cb } = captureStream()
    await proposalsStore.getState().generate(1)

    expect(proposalsStore.getState().startedAt).toEqual(expect.any(Number))
    cb().onProgress?.(PROGRESS)
    expect(proposalsStore.getState().progress).toEqual(PROGRESS)

    cb().onDone(5, [], 1)
    const state = proposalsStore.getState()
    expect(state.inFlight).toBe('idle')
    expect(state.progress).toBeNull()
    expect(state.startedAt).toBeNull()
  })

  it('un error a mitad de la redacción descarta el borrador parcial para poder reintentar', async () => {
    const { cb } = captureStream()
    await proposalsStore.getState().generate(1)
    cb().onToken('## Componentes\n- API ')

    cb().onError('La generación superó el tiempo máximo (5 min)')

    const state = proposalsStore.getState()
    expect(state.currentProposal).toBeNull()
    expect(state.error).toContain('tiempo máximo')
    expect(state.inFlight).toBe('idle')
  })

  it('un error limpia el progreso pero conserva el mensaje', async () => {
    const { cb } = captureStream()
    await proposalsStore.getState().generate(1)
    cb().onProgress?.(PROGRESS)

    cb().onError('La generación superó el tiempo máximo')

    const state = proposalsStore.getState()
    expect(state.error).toBe('La generación superó el tiempo máximo')
    expect(state.progress).toBeNull()
    expect(state.cancelled).toBe(false)
  })

  it('cancel() aborta el stream y deja la tarjeta lista para volver a generar', async () => {
    const { abort } = captureStream()
    await proposalsStore.getState().generate(1)

    proposalsStore.getState().cancel()

    const state = proposalsStore.getState()
    expect(abort).toHaveBeenCalledTimes(1)
    expect(state.inFlight).toBe('idle')
    expect(state.currentProposal).toBeNull()
    expect(state.cancelled).toBe(true)
    expect(state.error).toBeNull()
    expect(state.progress).toBeNull()
    expect(state.startedAt).toBeNull()
  })

  it('después de cancelar, los eventos tardíos del stream no tocan el estado', async () => {
    const { cb } = captureStream()
    await proposalsStore.getState().generate(1)
    const late = cb()

    proposalsStore.getState().cancel()
    late.onToken('texto tardío')
    late.onProgress?.(PROGRESS)
    late.onDone(99, [], 1)
    late.onError('boom')

    const state = proposalsStore.getState()
    expect(state.currentProposal).toBeNull()
    expect(state.iterations).toEqual([])
    expect(state.progress).toBeNull()
    expect(state.error).toBeNull()
  })

  it('cancelar una modificación conserva la versión vigente', async () => {
    const { abort } = captureStream()
    proposalsStore.setState({
      currentProposal: {
        id: 8,
        project_id: 1,
        iteration: 1,
        content_markdown: '## Componentes\n- Gateway',
        citations: [],
        lifecycle: 'proposed',
        feedback: null,
        created_at: null,
      },
    })
    await proposalsStore.getState().modify(8, 'agrega caché')

    proposalsStore.getState().cancel()

    const state = proposalsStore.getState()
    expect(abort).toHaveBeenCalledTimes(1)
    expect(state.currentProposal?.id).toBe(8)
    expect(state.currentProposal?.content_markdown).toContain('Gateway')
    expect(state.pendingProposal).toBeNull()
    expect(state.inFlight).toBe('idle')
    expect(state.cancelled).toBe(true)
  })

  it('cancel() resincroniza con el servidor por si el guardado ya había empezado', async () => {
    captureStream()
    await proposalsStore.getState().generate(1)

    proposalsStore.getState().cancel()

    await vi.waitFor(() => expect(api.getLatestProposal).toHaveBeenCalledWith(1))
    expect(proposalsStore.getState().currentProposal).toBeNull()
    expect(proposalsStore.getState().cancelled).toBe(true)
  })

  it('si la propuesta se guardó antes de que la cancelación llegara, se muestra y no se dice "cancelada"', async () => {
    vi.mocked(api.getLatestProposal).mockResolvedValue(out(41, 1, 'proposed'))
    vi.mocked(api.getProposalHistory).mockResolvedValue([out(41, 1, 'proposed')])
    captureStream()
    await proposalsStore.getState().generate(1)

    proposalsStore.getState().cancel()

    await vi.waitFor(() => expect(proposalsStore.getState().currentProposal?.id).toBe(41))
    const state = proposalsStore.getState()
    expect(state.cancelled).toBe(false)
    expect(state.inFlight).toBe('idle')
  })

  it('cancelar una modificación recarga la versión del servidor sin marcar "no cancelada" si no cambió', async () => {
    vi.mocked(api.getLatestProposal).mockResolvedValue(out(8, 1, 'proposed'))
    vi.mocked(api.getProposalHistory).mockResolvedValue([out(8, 1, 'proposed')])
    captureStream()
    proposalsStore.setState({
      currentProposal: {
        id: 8,
        project_id: 1,
        iteration: 1,
        content_markdown: '## Componentes\n- Gateway',
        citations: [],
        lifecycle: 'proposed',
        feedback: null,
        created_at: null,
      },
    })
    await proposalsStore.getState().modify(8, 'agrega caché')

    proposalsStore.getState().cancel()

    await vi.waitFor(() => expect(api.getLatestProposal).toHaveBeenCalledWith(1))
    expect(proposalsStore.getState().currentProposal?.id).toBe(8)
    expect(proposalsStore.getState().cancelled).toBe(true)
  })

  it('cancel() sin generación en curso no hace nada', () => {
    const { abort } = captureStream()
    proposalsStore.getState().cancel()
    expect(abort).not.toHaveBeenCalled()
    expect(proposalsStore.getState().cancelled).toBe(false)
  })

  it('una nueva generación borra la marca de cancelado', async () => {
    captureStream()
    await proposalsStore.getState().generate(1)
    proposalsStore.getState().cancel()
    expect(proposalsStore.getState().cancelled).toBe(true)

    await proposalsStore.getState().generate(1)
    expect(proposalsStore.getState().cancelled).toBe(false)
  })

  it('reset() aborta un stream vivo (cambio de proyecto)', async () => {
    const { abort } = captureStream()
    await proposalsStore.getState().generate(1)

    proposalsStore.getState().reset()

    expect(abort).toHaveBeenCalledTimes(1)
    expect(proposalsStore.getState().inFlight).toBe('idle')
  })

  it('lanzar otra generación mientras hay un stream vivo ABORTA el anterior', async () => {
    const abortFirst = vi.fn()
    const abortSecond = vi.fn()
    vi.mocked(api.createProposalStream)
      .mockReturnValueOnce(abortFirst)
      .mockReturnValueOnce(abortSecond)

    await proposalsStore.getState().generate(1)
    await proposalsStore.getState().generate(1)

    // Sin esto el fetch anterior seguía abierto y el backend gastando tokens.
    expect(abortFirst).toHaveBeenCalledTimes(1)
    expect(abortSecond).not.toHaveBeenCalled()
  })

  it('los eventos tardíos del stream reemplazado no tocan la nueva generación', async () => {
    const callbacks: StreamCallbacks[] = []
    vi.mocked(api.createProposalStream).mockImplementation((_e, _p, cb) => {
      callbacks.push(cb)
      return vi.fn()
    })

    await proposalsStore.getState().generate(1)
    await proposalsStore.getState().generate(1)
    callbacks[0].onToken('texto del stream viejo')
    callbacks[0].onDone(99, [], 1)

    const state = proposalsStore.getState()
    expect(state.currentProposal?.content_markdown).toBe('')
    expect(state.inFlight).toBe('generating')
    expect(state.iterations).toEqual([])
  })

  it('decidir limpia la marca de cancelado (no queda "Modificación cancelada" tras aprobar)', async () => {
    vi.mocked(api.decideProposal).mockResolvedValue({
      proposal_id: 8,
      lifecycle: 'approved',
      current_phase: null,
      phase_ready: true,
    })
    proposalsStore.setState({
      currentProposal: {
        id: 8,
        project_id: 1,
        iteration: 1,
        content_markdown: '## Componentes\n- Gateway',
        citations: [],
        lifecycle: 'proposed',
        feedback: null,
        created_at: null,
      },
      cancelled: true,
    })

    await proposalsStore.getState().decide(8, 'approve')

    expect(proposalsStore.getState().cancelled).toBe(false)
    expect(proposalsStore.getState().currentProposal?.lifecycle).toBe('approved')
  })
})

describe('proposalsStore reintento de una modificación (F19)', () => {
  const CURRENT = {
    id: 8,
    project_id: 1,
    iteration: 1,
    content_markdown: '## Componentes\n- Gateway',
    citations: [],
    lifecycle: 'proposed' as const,
    feedback: null,
    created_at: null,
  }

  beforeEach(() => {
    vi.clearAllMocks()
    proposalsStore.getState().reset()
    proposalsStore.setState({ currentProposal: CURRENT })
  })

  it('guarda el feedback mientras modifica y lo conserva si falla (tope de tiempo)', async () => {
    const { cb } = captureStream()
    await proposalsStore.getState().modify(8, 'agrega caché')
    expect(proposalsStore.getState().lastModify).toEqual({ proposalId: 8, feedback: 'agrega caché' })

    cb().onError('La generación superó el tiempo máximo (5 min)')

    const state = proposalsStore.getState()
    expect(state.lastModify).toEqual({ proposalId: 8, feedback: 'agrega caché' })
    expect(state.currentProposal?.id).toBe(8) // la versión vigente no se toca
    expect(state.error).toContain('tiempo máximo')
  })

  it('retry() vuelve a lanzar la modificación con el mismo feedback', async () => {
    const { cb } = captureStream()
    await proposalsStore.getState().modify(8, 'agrega caché')
    cb().onError('boom')
    vi.mocked(api.createProposalStream).mockClear()

    await proposalsStore.getState().retry()

    expect(api.createProposalStream).toHaveBeenCalledTimes(1)
    expect(vi.mocked(api.createProposalStream).mock.calls[0][0]).toBe('modify')
    expect(vi.mocked(api.createProposalStream).mock.calls[0][1]).toMatchObject({
      proposal_id: 8,
      feedback: 'agrega caché',
    })
    const state = proposalsStore.getState()
    expect(state.inFlight).toBe('modifying')
    expect(state.error).toBeNull()
  })

  it('cancelar una modificación también permite reintentarla', async () => {
    captureStream()
    await proposalsStore.getState().modify(8, 'agrega caché')

    proposalsStore.getState().cancel()

    expect(proposalsStore.getState().lastModify).toEqual({ proposalId: 8, feedback: 'agrega caché' })
  })

  it('al terminar bien, generar o decidir se olvida el feedback pendiente', async () => {
    const { cb } = captureStream()
    await proposalsStore.getState().modify(8, 'agrega caché')
    cb().onDone(9, [], 2)
    expect(proposalsStore.getState().lastModify).toBeNull()

    await proposalsStore.getState().modify(9, 'otro cambio')
    cb().onError('boom')
    expect(proposalsStore.getState().lastModify).not.toBeNull()
    await proposalsStore.getState().generate(1)
    expect(proposalsStore.getState().lastModify).toBeNull()
  })

  it('retry() sin nada que reintentar, o con una generación en curso, no hace nada', async () => {
    captureStream()
    await proposalsStore.getState().retry()
    expect(api.createProposalStream).not.toHaveBeenCalled()

    await proposalsStore.getState().modify(8, 'x')
    vi.mocked(api.createProposalStream).mockClear()
    await proposalsStore.getState().retry() // sigue en curso
    expect(api.createProposalStream).not.toHaveBeenCalled()
  })
})
