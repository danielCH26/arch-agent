import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../../api/proposals', () => ({
  createProposalStream: vi.fn(),
  decideProposal: vi.fn(),
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

  it('reset() NO aborta el stream: termina en segundo plano y se recuerda', () => {
    proposalsStore.getState().generate(PROJECT_ID)
    proposalsStore.getState().reset()

    expect(aborts[0]).not.toHaveBeenCalled()
    streams[0].onDone(11, [])
    expect(localStorage.getItem(`archagent:user:anon:last-proposal:${PROJECT_ID}`)).toBe('11')
  })
})
