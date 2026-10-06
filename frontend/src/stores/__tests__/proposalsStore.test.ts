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
