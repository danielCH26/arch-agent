import { vi } from 'vitest'

// HU10 (T8 commit 2c19482): <ChatWindow> now also calls
// ``fetchApprovalsHistory(projectId)`` at mount time. The real
// ``approvalsStore.fetchHistory`` re-throws on failure, and the call site
// is ``void fetchApprovalsHistory(...)`` with no catch handler -- so any
// rejected promise (e.g. unmocked fetch in jsdom) escapes as an unhandled
// rejection. Stub the store here, mirroring the pattern used in
// ``ChatWindow.mount-history.test.tsx`` for ``chatStore``.
const { fetchApprovalsHistoryMock } = vi.hoisted(() => ({
  fetchApprovalsHistoryMock: vi.fn().mockResolvedValue(undefined),
}))

vi.mock('../../stores/approvalsStore', () => {
  const actualState = {
    pendingDecision: {
      requerimientos: null,
      propuesta: null,
      refinamiento: null,
      revision: null,
      final: null,
    },
    historyByPhase: {
      requerimientos: [],
      propuesta: [],
      refinamiento: [],
      revision: [],
      final: [],
    },
    phases: [],
    currentPhase: null,
    loading: false,
    error: null,
    fetchHistory: (...args: unknown[]) =>
      fetchApprovalsHistoryMock(...args),
    setPending: vi.fn(),
    clearPending: vi.fn(),
    decide: vi.fn(),
    reset: vi.fn(),
  }
  // approvalsStore is consumed via the zustand selector pattern in
  // ChatWindow: ``approvalsStore((s) => s.fetchHistory)``. The mock must
  // actually invoke the selector (the existing chatStore mock did not
  // need this because ChatWindow reads chatStore via ``getState()``).
  const approvalsStoreFn = ((selector?: (s: typeof actualState) => unknown) =>
    selector ? selector(actualState) : actualState) as unknown as {
    (): typeof actualState
    (selector: (s: typeof actualState) => unknown): unknown
    getState: () => typeof actualState
    setState: ReturnType<typeof vi.fn>
  }
  approvalsStoreFn.getState = () => actualState
  approvalsStoreFn.setState = vi.fn()
  return { approvalsStore: approvalsStoreFn }
})

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { ChatWindow } from '../ChatWindow'
import { chatStore } from '../../stores/chatStore'
import { projectsStore } from '../../stores/projectsStore'
import { proposalsStore } from '../../stores/proposalsStore'
import * as proposalsApi from '../../api/proposals'

function resetStores() {
  chatStore.setState({
    messages: [],
    isStreaming: false,
    error: null,
    loadingHistory: false,
  })
  projectsStore.setState({
    projects: [],
    currentProject: null,
    status: 'idle',
    error: null,
  })
  proposalsStore.setState({
    currentProposal: null,
    iterations: [],
    inFlight: 'idle',
    error: null,
  })
}

describe('ChatWindow — SCN-8 ProposalCard mount condition', () => {
  beforeEach(() => resetStores())
  afterEach(() => {
    vi.restoreAllMocks()
    resetStores()
  })

  it('does NOT render ProposalCard when current_phase is not "propuesta" and no proposal is in flight', () => {
    projectsStore.setState({
      currentProject: {
        id: 1,
        name: 'demo',
        description: null,
        current_phase: 'requerimientos',
        phase_ready: false,
        created_at: '2026-09-05T00:00:00Z',
      },
    })

    render(<ChatWindow projectId={1} />)

    expect(screen.queryByTestId('proposal-card')).not.toBeInTheDocument()
  })

  it('renders ProposalCard when current_phase is "propuesta"', () => {
    projectsStore.setState({
      currentProject: {
        id: 1,
        name: 'demo',
        description: null,
        current_phase: 'propuesta',
        phase_ready: false,
        created_at: '2026-09-05T00:00:00Z',
      },
    })
    // Even with no proposal data yet, the card mounts to show the placeholder.
    render(<ChatWindow projectId={1} />)

    expect(screen.getByTestId('proposal-card')).toBeInTheDocument()
  })

  it('renders ProposalCard when a proposal is currently being streamed, even outside propuesta phase', () => {
    // Mount condition (REQ-7): also true while proposalsStore.inFlight !== idle.
    projectsStore.setState({
      currentProject: {
        id: 1,
        name: 'demo',
        description: null,
        current_phase: 'refinamiento',
        phase_ready: false,
        created_at: '2026-09-05T00:00:00Z',
      },
    })
    proposalsStore.setState({ inFlight: 'generating' })

    render(<ChatWindow projectId={1} />)

    expect(screen.getByTestId('proposal-card')).toBeInTheDocument()
  })

  it('still renders the normal chat bubble rows when ProposalCard is mounted', () => {
    projectsStore.setState({
      currentProject: {
        id: 1,
        name: 'demo',
        description: null,
        current_phase: 'propuesta',
        phase_ready: false,
        created_at: '2026-09-05T00:00:00Z',
      },
    })
    chatStore.setState({
      messages: [
        { id: 'm1', role: 'user', content: 'Genera una propuesta' },
        { id: 'm2', role: 'assistant', content: 'OK' },
      ],
    })

    render(<ChatWindow projectId={1} />)

    // The proposal card is there AND the existing chat bubbles are still
    // rendered -- this is the explicit "below the latest message" placement.
    expect(screen.getByTestId('proposal-card')).toBeInTheDocument()
    expect(screen.getByText('Genera una propuesta')).toBeInTheDocument()
    expect(screen.getByText('OK')).toBeInTheDocument()
  })

  it('wires projectId into ProposalCard so the "Generar propuesta" trigger is reachable from the propuesta phase', async () => {
    // Review fix (#68): ChatWindow mounted the card but never handed it the
    // projectId, so nothing in the UI could dispatch generate(). This pins
    // the end-to-end wiring: phase=propuesta -> card -> trigger -> store.
    const spy = vi
      .spyOn(proposalsApi, 'createProposalStream')
      .mockImplementation(() => undefined)
    projectsStore.setState({
      currentProject: {
        id: 42,
        name: 'demo',
        description: null,
        current_phase: 'propuesta',
        phase_ready: false,
        created_at: '2026-09-05T00:00:00Z',
      },
    })

    render(<ChatWindow projectId={42} />)

    const trigger = screen.getByTestId('proposal-generate')
    expect(trigger).toBeInTheDocument()

    fireEvent.click(trigger)

    await waitFor(() => {
      expect(spy).toHaveBeenCalledWith(
        'generate',
        { project_id: 42 },
        expect.anything(),
      )
    })
  })
})
