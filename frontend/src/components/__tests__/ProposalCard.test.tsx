import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ProposalCard } from '../ProposalCard'
import { proposalsStore } from '../../stores/proposalsStore'
import {
  createProposalStream,
  decideProposal,
  getProjectProposalState,
  getProposal,
  type ProjectProposalState,
  type ProposalOut,
} from '../../api/proposals'

vi.mock('../../api/proposals', () => ({
  createProposalStream: vi.fn(),
  decideProposal: vi.fn(),
  getProjectProposalState: vi.fn(),
  getProposal: vi.fn(),
}))

type Callbacks = Parameters<typeof createProposalStream>[2]

const PROJECT_ID = 7

const state = (overrides: Partial<ProjectProposalState> = {}): ProjectProposalState => ({
  approved: false,
  approved_at: null,
  approval_id: null,
  proposal_snapshot_chars: 0,
  last_decision: null,
  ...overrides,
})

const proposalOut = (overrides: Partial<ProposalOut> = {}): ProposalOut => ({
  id: 41,
  project_id: PROJECT_ID,
  iteration: 1,
  content: 'Arquitectura en capas',
  citations: [],
  feedback: null,
  lifecycle: 'proposed',
  created_at: '2026-10-01T10:00:00Z',
  ...overrides,
})

let streams: Callbacks[] = []

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  streams = []
  proposalsStore.getState().reset()
  vi.mocked(createProposalStream).mockImplementation((_mode, _payload, callbacks) => {
    streams.push(callbacks)
    return () => undefined
  })
  vi.mocked(getProjectProposalState).mockResolvedValue(state())
})

afterEach(() => {
  proposalsStore.getState().reset()
})

async function renderWithProposal(proposal: ProposalOut, projectState = state()) {
  vi.mocked(getProjectProposalState).mockResolvedValue(projectState)
  vi.mocked(getProposal).mockResolvedValue(proposal)
  // La tarjeta rehidrata la última propuesta recordada en el navegador.
  localStorage.setItem(`archagent:user:anon:last-proposal:${PROJECT_ID}`, String(proposal.id))
  render(<ProposalCard projectId={PROJECT_ID} />)
  await screen.findByTestId('proposal-content')
}

describe('ProposalCard', () => {
  it('pide confirmación antes de rechazar y no decide si se cancela', async () => {
    const user = userEvent.setup()
    await renderWithProposal(proposalOut())

    await user.click(screen.getByTestId('proposal-reject'))
    expect(screen.getByRole('alertdialog')).toBeInTheDocument()
    expect(decideProposal).not.toHaveBeenCalled()

    await user.click(screen.getByRole('button', { name: 'Cancelar' }))
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
    expect(decideProposal).not.toHaveBeenCalled()
  })

  it('rechaza solo tras confirmar', async () => {
    const user = userEvent.setup()
    vi.mocked(decideProposal).mockResolvedValue({ proposal_id: 41, lifecycle: 'rejected', current_phase: 'requerimientos', phase_ready: false })
    await renderWithProposal(proposalOut())

    await user.click(screen.getByTestId('proposal-reject'))
    await user.click(screen.getByTestId('proposal-reject-confirm-button'))

    expect(decideProposal).toHaveBeenCalledWith(41, 'reject', undefined)
  })

  it('usa el tope de iteraciones que informa el backend', async () => {
    await renderWithProposal(proposalOut({ iteration: 3 }), state({ max_iterations: 3 }))

    expect(screen.getByTestId('proposal-modify')).toBeDisabled()
    expect(screen.getByText(/máximo de 3 iteraciones/)).toBeInTheDocument()
  })

  it('no bloquea "Modificar" por su cuenta si el backend no informa el tope', async () => {
    await renderWithProposal(proposalOut({ iteration: 5 }))

    expect(screen.getByTestId('proposal-modify')).toBeEnabled()
  })

  it('recupera la propuesta generada mientras el usuario estaba en otra página', async () => {
    const user = userEvent.setup()
    vi.mocked(getProposal).mockResolvedValue(proposalOut())
    const first = render(<ProposalCard projectId={PROJECT_ID} />)
    await user.click(await screen.findByTestId('proposal-generate'))
    expect(streams).toHaveLength(1)

    // Sale de la página con la generación en curso y vuelve antes de que termine.
    first.unmount()
    render(<ProposalCard projectId={PROJECT_ID} />)
    expect(await screen.findByText('Generando propuesta...')).toBeInTheDocument()
    expect(screen.queryByTestId('proposal-generate')).not.toBeInTheDocument()

    act(() => streams[0].onDone(41, []))

    expect(await screen.findByTestId('proposal-content')).toHaveTextContent('Arquitectura en capas')
    expect(getProposal).toHaveBeenCalledWith(41)
    // Solo se generó una vez: no se gastó otra iteración.
    expect(createProposalStream).toHaveBeenCalledTimes(1)
  })

  it('recuerda la propuesta aunque termine sin la tarjeta montada', async () => {
    const user = userEvent.setup()
    const first = render(<ProposalCard projectId={PROJECT_ID} />)
    await user.click(await screen.findByTestId('proposal-generate'))
    first.unmount()

    act(() => streams[0].onDone(41, []))

    vi.mocked(getProposal).mockResolvedValue(proposalOut())
    render(<ProposalCard projectId={PROJECT_ID} />)
    await waitFor(() => expect(screen.getByTestId('proposal-content')).toHaveTextContent('Arquitectura en capas'))
  })
})
