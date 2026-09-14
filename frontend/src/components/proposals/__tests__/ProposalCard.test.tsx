import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ProposalCard } from '../ProposalCard'
import { proposalsStore } from '../../../stores/proposalsStore'
import * as proposalsApi from '../../../api/proposals'

function resetStore() {
  proposalsStore.setState({
    currentProposal: null,
    iterations: [],
    inFlight: 'idle',
    error: null,
  })
}

describe('ProposalCard', () => {
  beforeEach(() => resetStore())
  afterEach(() => {
    vi.restoreAllMocks()
    resetStore()
  })

  it('does not render when no proposal exists and forceMount is not set', () => {
    const { container } = render(<ProposalCard />)
    expect(container.firstChild).toBeNull()
  })

  it('renders the lifecycle "Propuesta" chip while generating', () => {
    proposalsStore.setState({
      currentProposal: {
        id: null,
        project_id: 1,
        iteration: 1,
        content_markdown: '## Componentes\n- API',
        citations: [],
        lifecycle: 'proposed',
        feedback: null,
        created_at: null,
      },
      inFlight: 'generating',
    })

    render(<ProposalCard forceMount />)

    expect(screen.getByTestId('proposal-card')).toBeInTheDocument()
    expect(screen.getByTestId('lifecycle-chip-proposed')).toBeInTheDocument()
  })

  it('renders three section headings (Componentes, Tecnologías, Patrones) and shows the proposal id once done', () => {
    proposalsStore.setState({
      currentProposal: {
        id: 99,
        project_id: 1,
        iteration: 1,
        content_markdown:
          '## Componentes\n- Servicio de autenticación\n\n## Tecnologias\n- Node.js\n- Postgres\n\n## Patrones\n- Hexagonal',
        citations: [
          { pattern_id: 1, pattern_name: 'Hexagonal', similarity: 0.91 },
        ],
        lifecycle: 'proposed',
        feedback: null,
        created_at: '2026-09-05T20:30:00Z',
      },
      inFlight: 'idle',
      iterations: [
        {
          id: 99,
          project_id: 1,
          iteration: 1,
          content_markdown: '',
          citations: [],
          lifecycle: 'proposed',
          feedback: null,
          created_at: '2026-09-05T20:30:00Z',
        },
      ],
    })

    render(<ProposalCard forceMount />)

    expect(
      screen.getByRole('heading', { name: 'Componentes' }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('heading', { name: 'Tecnologias' }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('heading', { name: 'Patrones' }),
    ).toBeInTheDocument()
    expect(screen.getByText(/Servicio de autenticación/)).toBeInTheDocument()
    // CitationList mounted -- the pattern name appears twice (once in the
    // markdown body under ## Patrones, once in the citation row), so we
    // assert presence via getAllByText.
    expect(screen.getAllByText(/Hexagonal/).length).toBeGreaterThan(0)
    // ProposalActions mounted (lifecycle=proposed and id set)
    expect(screen.getByTestId('proposal-approve')).toBeInTheDocument()
  })

  it('shows the "Aprobada" chip and hides actions after a successful approve', () => {
    proposalsStore.setState({
      currentProposal: {
        id: 99,
        project_id: 1,
        iteration: 1,
        content_markdown: '## Componentes\n- A',
        citations: [],
        lifecycle: 'approved',
        feedback: null,
        created_at: '2026-09-05T20:30:00Z',
      },
      inFlight: 'idle',
      iterations: [],
    })

    render(<ProposalCard forceMount />)

    expect(screen.getByTestId('lifecycle-chip-approved')).toBeInTheDocument()
    expect(screen.queryByTestId('proposal-approve')).not.toBeInTheDocument()
  })

  it('shows the "Rechazada" chip when lifecycle is rejected', () => {
    proposalsStore.setState({
      currentProposal: {
        id: 99,
        project_id: 1,
        iteration: 1,
        content_markdown: '## Componentes\n- A',
        citations: [],
        lifecycle: 'rejected',
        feedback: null,
        created_at: '2026-09-05T20:30:00Z',
      },
      inFlight: 'idle',
      iterations: [],
    })

    render(<ProposalCard forceMount />)

    expect(screen.getByTestId('lifecycle-chip-rejected')).toBeInTheDocument()
  })

  it('SCN-8: chatStore/proposalsStore-driven mount: ChatWindow is the gate (component returns null when nothing is in flight and no proposal exists)', () => {
    // REQ-7 / SCN-8: ChatWindow decides whether to render ProposalCard based on
    // current_phase. ProposalCard itself stays agnostic and returns null when
    // there's nothing to show, which is what this test pins.
    const { container } = render(<ProposalCard />)
    expect(container.firstChild).toBeNull()
  })

  it('shows the "Generar propuesta" trigger in the empty state and dispatches generate(projectId) on click', async () => {
    // Review fix (#68): nothing dispatched generate() from the UI, leaving
    // the card stuck on "Aún no hay propuesta." forever. The explicit button
    // (proposal.md decision #5) wires the empty state to the store action.
    const spy = vi
      .spyOn(proposalsApi, 'createProposalStream')
      .mockImplementation(() => undefined)

    render(<ProposalCard forceMount projectId={7} />)

    const button = screen.getByTestId('proposal-generate')
    expect(button).toBeInTheDocument()
    expect(button.textContent).toBe('Generar propuesta')

    fireEvent.click(button)

    await waitFor(() => {
      expect(spy).toHaveBeenCalledWith(
        'generate',
        { project_id: 7 },
        expect.anything(),
      )
    })
  })

  it('hides the "Generar propuesta" trigger while a stream is in flight', () => {
    proposalsStore.setState({ inFlight: 'generating' })

    render(<ProposalCard forceMount projectId={7} />)

    expect(screen.queryByTestId('proposal-generate')).not.toBeInTheDocument()
  })

  it('hides the "Generar propuesta" trigger when no projectId is provided (backwards compatible)', () => {
    render(<ProposalCard forceMount />)

    expect(screen.queryByTestId('proposal-generate')).not.toBeInTheDocument()
  })

  it('hides the "Generar propuesta" trigger once proposal content exists', () => {
    proposalsStore.setState({
      currentProposal: {
        id: 99,
        project_id: 7,
        iteration: 1,
        content_markdown: '## Componentes\n- A',
        citations: [],
        lifecycle: 'proposed',
        feedback: null,
        created_at: null,
      },
      inFlight: 'idle',
    })

    render(<ProposalCard forceMount projectId={7} />)

    expect(screen.queryByTestId('proposal-generate')).not.toBeInTheDocument()
  })

  it('surfaces the store error next to the trigger so a failed generation can be retried', () => {
    proposalsStore.setState({ error: 'SSE stream failed' })

    render(<ProposalCard forceMount projectId={7} />)

    expect(screen.getByTestId('proposal-generate-error')).toHaveTextContent(
      'SSE stream failed',
    )
    expect(screen.getByTestId('proposal-generate')).toBeInTheDocument()
  })
})