import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../../api/proposals', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/proposals')>()
  return {
    ...actual,
    createProposalStream: vi.fn(),
    getLatestProposal: vi.fn(),
    getProposalHistory: vi.fn(),
  }
})

import { getLatestProposal, getProposalHistory } from '../../api/proposals'
import { proposalsStore } from '../proposalsStore'

const getLatestProposalMock = vi.mocked(getLatestProposal)
const getProposalHistoryMock = vi.mocked(getProposalHistory)

describe('proposalsStore.loadLatest', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    proposalsStore.getState().reset()
  })

  it('keeps a rejected proposal in history without making it current', async () => {
    getLatestProposalMock.mockResolvedValue(null)
    getProposalHistoryMock.mockResolvedValue([
      {
        id: 12,
        project_id: 7,
        iteration: 1,
        content: 'Propuesta rechazada',
        citations: [],
        feedback: null,
        lifecycle: 'rejected',
        created_at: '2026-10-01T00:00:00Z',
      },
    ])

    await proposalsStore.getState().loadLatest(7)

    expect(proposalsStore.getState().currentProposal).toBeNull()
    expect(proposalsStore.getState().iterations).toHaveLength(1)
    expect(proposalsStore.getState().iterations[0].lifecycle).toBe('rejected')
  })
})
