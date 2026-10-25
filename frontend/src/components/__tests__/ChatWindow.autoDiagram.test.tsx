import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../../api/chat', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/chat')>()
  return { ...actual, fetchChatHistory: vi.fn().mockResolvedValue([]), createChatStream: vi.fn() }
})

vi.mock('../../api/diagrams', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/diagrams')>()
  return { ...actual, fetchDiagramHistory: vi.fn() }
})

import { AUTO_DIAGRAM_PROMPT, ChatWindow, isRefinementPhase } from '../ChatWindow'
import { fetchDiagramHistory } from '../../api/diagrams'
import { chatStore } from '../../stores/chatStore'
import { projectsStore } from '../../stores/projectsStore'
import { proposalsStore } from '../../stores/proposalsStore'

const sendMessage = vi.fn().mockResolvedValue(true)

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
  chatStore.setState({
    messages: [],
    isStreaming: false,
    error: null,
    loadingHistory: false,
    activeProjectId: null,
    // Evita llamar al LLM real: solo interesa si se envía el mensaje automático.
    sendMessage,
    loadHistory: vi.fn().mockResolvedValue(undefined),
  })
  projectsStore.setState({ projects: [], currentProject: null, status: 'idle', error: null })
  proposalsStore.getState().reset()
}

describe('ChatWindow — diagrama automático al entrar a Refinamiento', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    resetStores()
  })
  afterEach(() => resetStores())

  it('reconoce los nombres heredados de la fase', () => {
    expect(isRefinementPhase('refinamiento')).toBe(true)
    expect(isRefinementPhase('Diagrama')).toBe(true)
    expect(isRefinementPhase('propuesta')).toBe(false)
    expect(isRefinementPhase(null)).toBe(false)
  })

  it('pide el diagrama solo si el proyecto todavía no tiene ninguno', async () => {
    vi.mocked(fetchDiagramHistory).mockResolvedValue([])
    setPhase(3, 'refinamiento')

    render(<ChatWindow projectId={3} />)

    await waitFor(() => expect(sendMessage).toHaveBeenCalledWith(3, AUTO_DIAGRAM_PROMPT))
    expect(sendMessage).toHaveBeenCalledTimes(1)
  })

  it('no genera otro diagrama si ya existe uno (volver a entrar o F5)', async () => {
    vi.mocked(fetchDiagramHistory).mockResolvedValue([
      {
        message_id: 1,
        id: 'a',
        url: '/x.png',
        filename: null,
        created_at: '2026-10-16T00:00:00Z',
        decision: 'approve',
      },
    ])
    setPhase(3, 'refinamiento')

    render(<ChatWindow projectId={3} />)

    await waitFor(() => expect(fetchDiagramHistory).toHaveBeenCalledWith(3))
    await waitFor(() => expect(screen.queryByTestId('auto-diagram-checking')).not.toBeInTheDocument())
    expect(sendMessage).not.toHaveBeenCalled()
  })

  it('fuera de Refinamiento no consulta diagramas ni envía nada', async () => {
    setPhase(3, 'propuesta')

    render(<ChatWindow projectId={3} />)

    await new Promise((resolve) => setTimeout(resolve, 20))
    expect(fetchDiagramHistory).not.toHaveBeenCalled()
    expect(sendMessage).not.toHaveBeenCalled()
  })

  it('si falla la consulta de diagramas no rompe ni envía el mensaje', async () => {
    vi.mocked(fetchDiagramHistory).mockRejectedValue(new Error('boom'))
    setPhase(3, 'refinamiento')

    render(<ChatWindow projectId={3} />)

    await waitFor(() => expect(screen.queryByTestId('auto-diagram-checking')).not.toBeInTheDocument())
    expect(sendMessage).not.toHaveBeenCalled()
  })
})
