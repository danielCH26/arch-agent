import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ChatWindow } from '../ChatWindow'
import { chatStore } from '../../stores/chatStore'
import { projectsStore } from '../../stores/projectsStore'
import { proposalsStore } from '../../stores/proposalsStore'
import * as chatApi from '../../api/chat'

const RESUMEN = {
  problema: 'Plataforma de cadena de frío',
  usuarios: 'Operadores',
  funcionalidades: ['Alertas'],
  restricciones: ['MVP en 6 meses'],
  calidad: ['99.99%'],
}

const DONE_STATE: chatApi.ElicitationState = {
  done: true,
  question: null,
  resumen: RESUMEN,
  history: [{ pregunta: 'P1', respuesta: 'R1' }],
}

function resetStores() {
  chatStore.setState({ messages: [], isStreaming: false, error: null })
  projectsStore.setState({ projects: [], currentProject: null, status: 'idle', error: null })
  proposalsStore.setState({ currentProposal: null, iterations: [], inFlight: 'idle', error: null })
}

describe('ChatWindow — fase requerimientos (aprobación y avance)', () => {
  beforeEach(() => resetStores())
  afterEach(() => {
    vi.restoreAllMocks()
    resetStores()
  })

  it('con el resumen pendiente muestra Aprobar/Modificar/Rechazar y no el botón de avanzar', async () => {
    vi.spyOn(chatApi, 'getElicitationState').mockResolvedValue(DONE_STATE)

    render(<ChatWindow projectId={1} phase="requerimientos" phaseReady={false} onAdvance={vi.fn()} />)

    expect(await screen.findByText('Aprobar')).toBeTruthy()
    expect(screen.queryByTestId('advance-phase')).toBeNull()
  })

  it('con phase_ready=true NO vuelve a pedir la decisión y ofrece continuar a Propuesta', async () => {
    vi.spyOn(chatApi, 'getElicitationState').mockResolvedValue(DONE_STATE)
    const onAdvance = vi.fn().mockResolvedValue(undefined)

    render(<ChatWindow projectId={1} phase="requerimientos" phaseReady onAdvance={onAdvance} />)

    const advance = await screen.findByTestId('advance-phase')
    expect(screen.queryByText('Aprobar')).toBeNull()
    expect(advance.textContent).toContain('Propuesta')

    fireEvent.click(advance)
    await waitFor(() => expect(onAdvance).toHaveBeenCalledTimes(1))
  })

  it('tras aprobar, pide recargar el proyecto y muestra el botón de avanzar', async () => {
    vi.spyOn(chatApi, 'getElicitationState').mockResolvedValue(DONE_STATE)
    vi.spyOn(chatApi, 'submitElicitationDecision').mockResolvedValue({
      decision: 'approve',
      phase_ready: true,
      message: 'ok',
    })
    const onProjectUpdated = vi.fn().mockResolvedValue(undefined)

    render(
      <ChatWindow
        projectId={1}
        phase="requerimientos"
        phaseReady={false}
        onAdvance={vi.fn()}
        onProjectUpdated={onProjectUpdated}
      />,
    )

    fireEvent.click(await screen.findByText('Aprobar'))

    expect(await screen.findByTestId('advance-phase')).toBeTruthy()
    expect(onProjectUpdated).toHaveBeenCalled()
    expect(screen.queryByText('Aprobar')).toBeNull()
  })

  it('si tras modificar falla la regeneración, no deja el resumen viejo pegado y ofrece Reintentar', async () => {
    const getState = vi
      .spyOn(chatApi, 'getElicitationState')
      .mockResolvedValueOnce(DONE_STATE)
      .mockResolvedValue({ done: false, question: null, resumen: null, history: [] })
    vi.spyOn(chatApi, 'submitElicitationDecision').mockResolvedValue({
      decision: 'modify',
      phase_ready: false,
      message: 'Se registró tu ajuste. Llama a /elicitation/message para continuar.',
    })
    const send = vi
      .spyOn(chatApi, 'sendElicitationMessage')
      .mockRejectedValueOnce(new Error('El modelo de IA no está disponible'))
      .mockResolvedValue({ ...DONE_STATE, resumen: { ...RESUMEN, restricciones: ['MVP en 8 meses'] } })

    render(<ChatWindow projectId={1} phase="requerimientos" phaseReady={false} />)

    fireEvent.click(await screen.findByText('Modificar'))
    fireEvent.change(await screen.findByPlaceholderText(/Describe los cambios/), {
      target: { value: 'ahora son 8 meses' },
    })
    fireEvent.click(screen.getByText('Enviar ajuste'))

    // Falla la regeneración: error visible + Reintentar, sin resumen viejo ni texto crudo del backend.
    expect(await screen.findByText('El modelo de IA no está disponible')).toBeTruthy()
    expect(screen.queryByText('Resumen de requerimientos para validar')).toBeNull()
    expect(screen.queryByText(/Llama a \/elicitation\/message/)).toBeNull()

    fireEvent.click(screen.getByText('Reintentar'))
    expect(await screen.findByText('MVP en 8 meses')).toBeTruthy()
    expect(send).toHaveBeenCalledTimes(2)
    expect(getState).toHaveBeenCalled()
  })
})

describe('ChatWindow — fase propuesta', () => {
  beforeEach(() => resetStores())
  afterEach(() => {
    vi.restoreAllMocks()
    resetStores()
  })

  it('rehidrata la propuesta existente al entrar a la fase y ofrece continuar si ya está aprobada', async () => {
    vi.spyOn(chatStore.getState(), 'loadHistory').mockResolvedValue(undefined)
    const proposalsApi = await import('../../api/proposals')
    vi.spyOn(proposalsApi, 'getLatestProposal').mockResolvedValue({
      id: 7,
      project_id: 1,
      iteration: 1,
      content: '## Componentes\n- API',
      citations: [],
      feedback: null,
      lifecycle: 'approved',
      created_at: '2026-09-28T00:00:00',
    })

    render(<ChatWindow projectId={1} phase="propuesta" phaseReady onAdvance={vi.fn()} />)

    await waitFor(() => expect(proposalsStore.getState().currentProposal?.id).toBe(7))
    const advance = await screen.findByTestId('advance-phase')
    expect(advance.textContent).toContain('Refinamiento')
  })
})

describe('ChatWindow — fase refinamiento (diagrama automático)', () => {
  const originalSendMessage = chatStore.getState().sendMessage
  const originalLoadHistory = chatStore.getState().loadHistory

  beforeEach(() => resetStores())
  afterEach(() => {
    vi.restoreAllMocks()
    chatStore.setState({ sendMessage: originalSendMessage, loadHistory: originalLoadHistory })
    resetStores()
  })

  it('al entrar sin diagramas genera el diagrama solo, sin que el usuario lo pida', async () => {
    const sendMessage = vi.fn().mockResolvedValue(undefined)
    chatStore.setState({ sendMessage, loadHistory: vi.fn().mockResolvedValue(undefined) })
    const diagramsApi = await import('../../api/diagrams')
    vi.spyOn(diagramsApi, 'fetchDiagramHistory').mockResolvedValue([])

    render(<ChatWindow projectId={1} phase="refinamiento" />)

    await waitFor(() => expect(sendMessage).toHaveBeenCalledTimes(1))
    expect(sendMessage.mock.calls[0][0]).toBe(1)
    expect(sendMessage.mock.calls[0][1]).toContain('diagrama')
  })

  it('trata la fase heredada "diagram" como refinamiento', async () => {
    const sendMessage = vi.fn().mockResolvedValue(undefined)
    chatStore.setState({ sendMessage, loadHistory: vi.fn().mockResolvedValue(undefined) })
    const diagramsApi = await import('../../api/diagrams')
    vi.spyOn(diagramsApi, 'fetchDiagramHistory').mockResolvedValue([])

    render(<ChatWindow projectId={1} phase="diagram" />)

    await waitFor(() => expect(sendMessage).toHaveBeenCalledWith(1, expect.stringContaining('diagrama')))
  })

  it('si el proyecto ya tiene diagramas no vuelve a generarlo', async () => {
    const sendMessage = vi.fn().mockResolvedValue(undefined)
    chatStore.setState({ sendMessage, loadHistory: vi.fn().mockResolvedValue(undefined) })
    const diagramsApi = await import('../../api/diagrams')
    const fetchHistory = vi.spyOn(diagramsApi, 'fetchDiagramHistory').mockResolvedValue([
      {
        message_id: 1,
        id: 'abc',
        url: '/x.png',
        filename: 'x.png',
        created_at: '2026-09-28T00:00:00',
        decision: null,
      },
    ])

    render(<ChatWindow projectId={1} phase="refinamiento" />)

    await waitFor(() => expect(fetchHistory).toHaveBeenCalled())
    expect(sendMessage).not.toHaveBeenCalled()
    expect(await screen.findByTestId('approved-diagram')).toBeInTheDocument()
    expect(screen.getByText('Diagrama de la propuesta aprobada')).toBeInTheDocument()
    expect(screen.getByAltText('Diagrama de la estructura aprobada')).toHaveAttribute('src', '/x.png')
  })

  it('el diagrama aprobado que se recarga tiene tope de tamano (no se estira a toda la pantalla)', async () => {
    chatStore.setState({ sendMessage: vi.fn(), loadHistory: vi.fn().mockResolvedValue(undefined) })
    const diagramsApi = await import('../../api/diagrams')
    vi.spyOn(diagramsApi, 'fetchDiagramHistory').mockResolvedValue([
      {
        message_id: 1,
        id: 'abc',
        url: '/x.png',
        filename: 'x.png',
        created_at: '2026-09-28T00:00:00',
        decision: null,
      },
    ])

    render(<ChatWindow projectId={1} phase="refinamiento" />)

    const img = await screen.findByAltText('Diagrama de la estructura aprobada')
    expect(img.className).toContain('max-w-3xl')
    expect(img.className).toContain('max-h-[70vh]')
  })

  it('en otras fases no genera el diagrama', async () => {
    const sendMessage = vi.fn().mockResolvedValue(undefined)
    chatStore.setState({ sendMessage, loadHistory: vi.fn().mockResolvedValue(undefined) })
    const diagramsApi = await import('../../api/diagrams')
    const fetchHistory = vi.spyOn(diagramsApi, 'fetchDiagramHistory').mockResolvedValue([])
    vi.spyOn(chatApi, 'getElicitationState').mockResolvedValue(DONE_STATE)

    render(<ChatWindow projectId={1} phase="requerimientos" />)

    await screen.findByText('Aprobar')
    expect(fetchHistory).not.toHaveBeenCalled()
    expect(sendMessage).not.toHaveBeenCalled()
  })
})
