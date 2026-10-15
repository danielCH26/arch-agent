/**
 * Deciding a proposal must re-sync the HU10 stores.
 *
 * On `propuesta`, <ProposalCard> and <PhaseActions> read the same server
 * state (pending decision, phase_ready, current_phase). `proposalsStore.decide`
 * used to refresh neither, so after approving from the proposal card the
 * phase surface kept stale pending buttons and "Avanzar" never appeared.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../../api/proposals', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api/proposals')>()),
  decideProposal: vi.fn(),
}))

import { decideProposal } from '../../api/proposals'
import { useApprovalsStore } from '../approvalsStore'
import { projectsStore } from '../projectsStore'
import { proposalsStore } from '../proposalsStore'

const DECISION_RESPONSE = {
  proposal_id: 5,
  lifecycle: 'approved',
  current_phase: 'propuesta',
  phase_ready: true,
}

describe('proposalsStore.decide syncs the HU10 stores', () => {
  beforeEach(() => {
    vi.mocked(decideProposal).mockReset()
    vi.mocked(decideProposal).mockResolvedValue(DECISION_RESPONSE as never)
    proposalsStore.setState({
      current: null,
      iterations: [],
      activity: 'idle',
      error: null,
    })
  })

  it('refreshes approvals and the current project after a successful decision', async () => {
    const refresh = vi.fn().mockResolvedValue(undefined)
    const getProject = vi.fn().mockResolvedValue(null)
    useApprovalsStore.setState({ refresh })
    projectsStore.setState({
      currentProject: { id: 7 } as never,
      getProject,
    })

    await proposalsStore.getState().decide(5, 'approve')

    expect(refresh).toHaveBeenCalledTimes(1)
    expect(getProject).toHaveBeenCalledWith(7)
  })

  it('does nothing extra when no project is loaded, and still resolves', async () => {
    const refresh = vi.fn().mockResolvedValue(undefined)
    const getProject = vi.fn()
    useApprovalsStore.setState({ refresh })
    projectsStore.setState({ currentProject: null, getProject })

    await expect(proposalsStore.getState().decide(5, 'approve')).resolves.toBeTruthy()

    expect(getProject).not.toHaveBeenCalled()
  })

  it('a failing sync never fails the decision', async () => {
    useApprovalsStore.setState({ refresh: vi.fn().mockRejectedValue(new Error('boom')) })
    projectsStore.setState({
      currentProject: { id: 7 } as never,
      getProject: vi.fn().mockRejectedValue(new Error('boom')),
    })

    await expect(proposalsStore.getState().decide(5, 'approve')).resolves.toBeTruthy()
    expect(proposalsStore.getState().error).toBeNull()
  })

  it('does not sync when the decision itself fails', async () => {
    const refresh = vi.fn().mockResolvedValue(undefined)
    useApprovalsStore.setState({ refresh })
    vi.mocked(decideProposal).mockRejectedValue(new Error('409'))

    await expect(proposalsStore.getState().decide(5, 'approve')).rejects.toThrow('409')

    expect(refresh).not.toHaveBeenCalled()
  })
})
