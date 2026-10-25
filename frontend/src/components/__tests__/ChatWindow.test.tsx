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

vi.mock('../../api/documents', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/documents')>()
  return { ...actual, listDocuments: vi.fn().mockResolvedValue([]) }
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

describe('ChatWindow — chat libre y documentos por fase', () => {
  beforeEach(() => resetStores())
  afterEach(() => {
    vi.clearAllMocks()
    resetStores()
  })

  // Bug real: Propuesta ya se maneja 100% con los botones de ProposalCard
  // (Aprobar / Solicitar cambios / Rechazar), pero el ChatInput libre seguía
  // disponible debajo -- un mensaje suelto ahí podía desviar al agente sin
  // que ningún flujo lo esperara.
  it('no muestra el chat libre en Propuesta', () => {
    setPhase(1, 'propuesta')
    render(<ChatWindow projectId={1} />)

    expect(screen.queryByLabelText('Mensaje para ArchAgent')).not.toBeInTheDocument()
  })

  it('sí muestra el chat libre fuera de Propuesta (p. ej. Refinamiento)', () => {
    setPhase(1, 'refinamiento')
    render(<ChatWindow projectId={1} />)

    expect(screen.getByLabelText('Mensaje para ArchAgent')).toBeInTheDocument()
  })

  // Los documentos ya no son solo de Elicitación: el agente busca en ellos
  // por similitud sin importar la fase, así que la caja de subida debe estar
  // disponible en todo el flujo -- completa en Propuesta (no hay ChatInput
  // ahí para adjuntar con el clip) y compacta en el resto.
  it('en Propuesta usa la caja completa de documentos, con su propio botón de subir', async () => {
    setPhase(1, 'propuesta')
    render(<ChatWindow projectId={1} />)

    expect(await screen.findByText('¿Tienes documentos del proyecto? (opcional)')).toBeInTheDocument()
  })

  it('fuera de Propuesta, con documentos ya subidos, usa la caja compacta', async () => {
    const { listDocuments } = await import('../../api/documents')
    vi.mocked(listDocuments).mockResolvedValueOnce([
      {
        id: 1,
        filename: 'acta.pdf',
        file_type: 'pdf',
        file_size_bytes: 10,
        chunk_count: 1,
        version: 1,
        processed: true,
        created_at: '2026-10-21T00:00:00Z',
      },
    ])
    setPhase(1, 'refinamiento')
    render(<ChatWindow projectId={1} />)

    expect(await screen.findByText('Documentos que el agente tiene en cuenta:')).toBeInTheDocument()
    expect(screen.queryByText('¿Tienes documentos del proyecto? (opcional)')).not.toBeInTheDocument()
  })
})
