import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../../api/chat', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/chat')>()
  return { ...actual, fetchChatHistory: vi.fn().mockResolvedValue([]), createChatStream: vi.fn() }
})
vi.mock('../../api/adr', () => ({
  getAdr: vi.fn().mockResolvedValue({ markdown: null, generated_at: null, guide_complete: false }),
  generateAdr: vi.fn(),
}))
vi.mock('../../api/diagrams', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/diagrams')>()
  return { ...actual, fetchDiagramHistory: vi.fn().mockResolvedValue([]) }
})

import { ChatWindow } from '../ChatWindow'
import { chatStore } from '../../stores/chatStore'
import { projectsStore } from '../../stores/projectsStore'
import { proposalsStore } from '../../stores/proposalsStore'

const OLD_MESSAGES = [
  { id: 'm1', role: 'user' as const, content: 'genera el diagrama de la propuesta aprobada' },
  { id: 'm2', role: 'assistant' as const, content: 'Respuesta de refinamiento' },
]

function setup(phase: string) {
  projectsStore.setState({
    projects: [],
    status: 'idle',
    error: null,
    currentProject: {
      id: 3,
      name: 'Clínica',
      description: null,
      current_phase: phase,
      phase_ready: false,
      created_at: '2026-09-05T00:00:00Z',
    },
  })
  chatStore.setState({
    messages: OLD_MESSAGES,
    isStreaming: false,
    error: null,
    loadingHistory: false,
    activeProjectId: 3,
    // El historial ya está cargado para este proyecto.
    loadHistory: vi.fn().mockResolvedValue(undefined),
    // Evita el diagrama automático real en el caso de Refinamiento.
    sendMessage: vi.fn().mockResolvedValue(true),
  })
  proposalsStore.getState().reset()
}

describe('ChatWindow — fase Revisión', () => {
  beforeEach(() => vi.clearAllMocks())

  it('muestra el ADR y oculta la conversación de las fases anteriores', async () => {
    setup('revision')
    render(<ChatWindow projectId={3} />)

    expect(await screen.findByTestId('adr-panel')).toBeInTheDocument()
    expect(screen.queryByText('Respuesta de refinamiento')).not.toBeInTheDocument()
    expect(screen.getByTestId('toggle-prior-chat')).toHaveTextContent('(2 mensajes)')
    // Sin el texto de "comenzar la conversación": el contenido es el ADR.
    expect(screen.queryByText(/Envía un mensaje para comenzar/)).not.toBeInTheDocument()
  })

  it('permite ver la conversación anterior con el botón', async () => {
    setup('revision')
    render(<ChatWindow projectId={3} />)

    await userEvent.click(await screen.findByTestId('toggle-prior-chat'))

    expect(screen.getByText('Respuesta de refinamiento')).toBeInTheDocument()
  })

  it('en Refinamiento se ve la conversación completa', () => {
    setup('refinamiento')
    render(<ChatWindow projectId={3} />)

    expect(screen.getByText('Respuesta de refinamiento')).toBeInTheDocument()
    expect(screen.queryByTestId('toggle-prior-chat')).not.toBeInTheDocument()
  })
})
