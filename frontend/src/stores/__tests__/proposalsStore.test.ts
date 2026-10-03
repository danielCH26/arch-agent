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
})
