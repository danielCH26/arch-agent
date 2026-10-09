import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../../api/chat', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/chat')>()
  return { ...actual, fetchChatHistory: vi.fn().mockResolvedValue([]), createChatStream: vi.fn() }
})

vi.mock('../../api/proposals', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/proposals')>()
  return {
    ...actual,
    createProposalStream: vi.fn(() => () => undefined),
    getProposal: vi.fn(),
    getProjectProposalState: vi.fn().mockResolvedValue({
      approved: false,
      approved_at: null,
      approval_id: null,
      proposal_snapshot_chars: 0,
      last_decision: null,
    }),
  }
})

import { ChatWindow } from '../ChatWindow'
import { chatStore } from '../../stores/chatStore'
import { projectsStore } from '../../stores/projectsStore'
import { proposalsStore } from '../../stores/proposalsStore'
import { createProposalStream } from '../../api/proposals'

function setPhase(id: number, current_phase: string) {
  projectsStore.setState({
    currentProject: {
      id,
      name: 'demo',
      description: null,
      current_phase,
      phase_ready: false,
      created_at: '2026-09-05T00:00:00Z',
    },
  })
}

function resetStores() {
  chatStore.setState({ messages: [], isStreaming: false, error: null, loadingHistory: false, activeProjectId: null })
  projectsStore.setState({ projects: [], currentProject: null, status: 'idle', error: null })
  proposalsStore.getState().reset()
}

describe('ChatWindow — SCN-8 ProposalCard mount condition', () => {
  beforeEach(() => resetStores())
  afterEach(() => {
    vi.clearAllMocks()
    resetStores()
  })

  it('does NOT render ProposalCard when current_phase is not "propuesta" and no proposal is in flight', () => {
    setPhase(1, 'requerimientos')
    render(<ChatWindow projectId={1} />)

    expect(screen.queryByTestId('proposal-card')).not.toBeInTheDocument()
  })

  it('renders ProposalCard when current_phase is "propuesta"', () => {
    setPhase(1, 'propuesta')
    // Even with no proposal data yet, the card mounts to show the placeholder.
    render(<ChatWindow projectId={1} />)

    expect(screen.getByTestId('proposal-card')).toBeInTheDocument()
  })

  it('renders ProposalCard when a proposal is currently being streamed, even outside propuesta phase', () => {
    setPhase(1, 'refinamiento')
    proposalsStore.setState({
      activity: 'generating',
      current: { id: null, projectId: 1, iteration: 1, content: '', citations: [], feedback: null, lifecycle: 'proposed' },
    })

    render(<ChatWindow projectId={1} />)

    expect(screen.getByTestId('proposal-card')).toBeInTheDocument()
  })

  it('still renders the normal chat bubble rows when ProposalCard is mounted', () => {
    setPhase(1, 'propuesta')
    // activeProjectId evita que ChatWindow recargue el historial al montar.
    chatStore.setState({
      activeProjectId: 1,
      loadingHistory: true,
      messages: [
        { id: 'm1', role: 'user', content: 'Genera una propuesta' },
        { id: 'm2', role: 'assistant', content: 'OK' },
      ],
    })

    render(<ChatWindow projectId={1} />)

    expect(screen.getByTestId('proposal-card')).toBeInTheDocument()
    expect(screen.getByText('Genera una propuesta')).toBeInTheDocument()
    expect(screen.getByText('OK')).toBeInTheDocument()
  })

  it('wires projectId into ProposalCard so the "Generar propuesta" trigger is reachable from the propuesta phase', async () => {
    setPhase(42, 'propuesta')
    render(<ChatWindow projectId={42} />)

    const trigger = await screen.findByTestId('proposal-generate')
    fireEvent.click(trigger)

    await waitFor(() => {
      expect(createProposalStream).toHaveBeenCalledWith('generate', { projectId: 42 }, expect.anything())
    })
  })
})
