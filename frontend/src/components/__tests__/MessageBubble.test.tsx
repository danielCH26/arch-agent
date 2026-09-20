import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { MessageBubble } from '../MessageBubble'
import { submitDiagramDecision } from '../../api/diagrams'
import type { Attachment, Message } from '../../stores/chatStore'

// Las decisiones sobre el diagrama pegan a POST /api/diagrams/decision; aqui se
// mockea la API para probar el comportamiento de la burbuja.
vi.mock('../../api/diagrams', () => ({
  submitDiagramDecision: vi.fn().mockResolvedValue(undefined),
}))

const submitDecisionMock = vi.mocked(submitDiagramDecision)

beforeEach(() => {
  submitDecisionMock.mockReset()
  submitDecisionMock.mockResolvedValue(undefined)
})

function renderMessage(
  content: string,
  role: Message['role'] = 'assistant',
  attachments?: Attachment[],
  onSendMessage?: (text: string, displayText?: string) => void,
  projectId: number | undefined = 1
) {
  render(
    <MessageBubble
      message={{ id: 'message-1', role, content, attachments }}
      projectId={projectId}
      onSendMessage={onSendMessage}
    />
  )
}

describe('MessageBubble', () => {
  it('renders assistant markdown headings and strong text', () => {
    renderMessage('### Patrón recomendado\n**Frontend-specific back-end**')

    expect(screen.getByRole('heading', { name: 'Patrón recomendado' })).toBeInTheDocument()
    expect(screen.getByText('Frontend-specific back-end').tagName).toBe('STRONG')
  })

  it('renders markdown tables as semantic tables', () => {
    renderMessage('| Nivel | Patrón |\n|---|---|\n| 1 | BFF |\n| 2 | Hexagonal |')

    const table = screen.getByRole('table')

    expect(within(table).getByRole('columnheader', { name: 'Nivel' })).toBeInTheDocument()
    expect(within(table).getByRole('cell', { name: 'BFF' })).toBeInTheDocument()
    expect(screen.queryByText('| Nivel | Patrón |')).not.toBeInTheDocument()
  })

  it('renders html line breaks and html tables in assistant messages', () => {
    renderMessage('Uno<br>Dos\n<table><tr><th>Área</th></tr><tr><td>Pagos</td></tr></table>')

    expect(screen.getByText(/Uno Dos/)).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'Área' })).toBeInTheDocument()
    expect(screen.getByRole('cell', { name: 'Pagos' })).toBeInTheDocument()
  })

  it('keeps user messages as plain text', () => {
    renderMessage('### No renderizar\n**literal**', 'user')

    expect(screen.getByText(/### No renderizar/)).toBeInTheDocument()
    expect(screen.queryByRole('heading')).not.toBeInTheDocument()
  })

  // ----- F13 (REQ-PMCP-1 / REQ-ATT-3) attachment rendering ---------------

  it('does not render any <img> when attachments is empty', () => {
    renderMessage('Sin diagrama.', 'assistant', [])
    expect(screen.queryByRole('img')).not.toBeInTheDocument()
  })

  it('does not render any <img> when attachments is undefined', () => {
    renderMessage('Sin diagrama.', 'assistant', undefined)
    expect(screen.queryByRole('img')).not.toBeInTheDocument()
  })

  it('renders one <img> per attachment with the signed URL + alt text', () => {
    const attachments: Attachment[] = [
      {
        kind: 'screenshot',
        mime: 'image/png',
        url: '/api/chat/attachments/abc-uuid?token=signed.jwt',
        filename: 'diagram-12345.png',
      },
    ]
    renderMessage('Aquí va el diagrama:', 'assistant', attachments)
    const img = screen.getByRole('img')
    expect(img).toHaveAttribute(
      'src',
      '/api/chat/attachments/abc-uuid?token=signed.jwt'
    )
    expect(img).toHaveAttribute('alt', 'diagram-12345.png')
    expect(img).toHaveAttribute('loading', 'lazy')
    expect(img).toHaveAttribute('title', 'Click para ampliar')
  })

  it('expands diagram attachments on click and closes the overlay', async () => {
    const user = userEvent.setup()
    const attachments: Attachment[] = [
      {
        kind: 'screenshot',
        mime: 'image/png',
        url: '/api/chat/attachments/abc-uuid?token=signed.jwt',
        filename: 'diagram-12345.png',
      },
    ]

    renderMessage('Aquí va el diagrama:', 'assistant', attachments)

    await user.click(screen.getByRole('img', { name: 'diagram-12345.png' }))

    const expanded = screen.getByRole('img', { name: 'Diagrama ampliado' })
    expect(expanded).toHaveAttribute('src', '/api/chat/attachments/abc-uuid?token=signed.jwt')

    expect(screen.getByText('Controles')).toBeInTheDocument()
    expect(screen.getByRole('status', { name: 'Zoom actual 200%' })).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Acercar diagrama' }))

    expect(screen.getByRole('status', { name: 'Zoom actual 250%' })).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Cerrar visor de diagrama' }))

    expect(screen.queryByRole('img', { name: 'Diagrama ampliado' })).not.toBeInTheDocument()
  })

  it('sends the previous Mermaid source when requesting diagram changes', async () => {
    const user = userEvent.setup()
    const onSendMessage = vi.fn()
    const attachments: Attachment[] = [
      {
        kind: 'screenshot',
        mime: 'image/png',
        url: '/api/chat/attachments/abc-uuid?token=signed.jwt',
        filename: 'diagram-12345.png',
      },
    ]
    const content = [
      'Diagrama:',
      '```mermaid',
      'flowchart TD',
      '  API_Gateway["API Gateway"] --> Order_Service["Order Service"]',
      '  Order_Service --> Payment_Service["Payment Service"]',
      '```',
    ].join('\n')

    renderMessage(content, 'assistant', attachments, onSendMessage)

    await user.click(screen.getByRole('button', { name: '✏️ Solicitar cambios' }))
    await user.type(screen.getByLabelText('¿Qué debe ajustarse en el diagrama?'), 'Agrega Redis entre gateway y ordenes')
    await user.click(screen.getByRole('button', { name: 'Enviar ajuste' }))

    // El prompt se manda al agente despues de registrar la decision (POST async).
    await waitFor(() => expect(onSendMessage).toHaveBeenCalledTimes(1))
    const prompt = onSendMessage.mock.calls[0][0]
    expect(prompt).toContain('Responde UNICAMENTE con un bloque ```mermaid```')
    expect(prompt).toContain('No agregues explicaciones')
    expect(prompt).toContain('Conserva todos los nodos')
    expect(prompt).toContain('No simplifiques ni reescribas')
    expect(prompt).toContain('Agrega Redis entre gateway y ordenes')
    expect(prompt).toContain('flowchart TD')
    expect(prompt).toContain('API_Gateway["API Gateway"] --> Order_Service["Order Service"]')
    expect(prompt).toContain('Order_Service --> Payment_Service["Payment Service"]')
  })

  it('does not render attachments on user messages', () => {
    const attachments: Attachment[] = [
      {
        kind: 'screenshot',
        mime: 'image/png',
        url: '/api/chat/attachments/abc?token=t',
        filename: 'diagram-12345.png',
      },
    ]
    renderMessage('Hola', 'user', attachments)
    // The <img> slot only fires for assistant messages — users keep their
    // raw content as plain text.
    expect(screen.queryByRole('img')).not.toBeInTheDocument()
  })

  // ---------------------------------------------------------------------
  // Decision POR diagrama (QA HU6): antes, tras rechazar y hacer F5, volvian
  // los tres botones porque el estado "ya decidido" solo vivia en React.
  // ---------------------------------------------------------------------
  describe('decision persistida del diagrama', () => {
    const diagram = (extra: Partial<Attachment> = {}): Attachment[] => [
      {
        id: 'att-1',
        kind: 'screenshot',
        mime: 'image/png',
        url: '/api/chat/attachments/att-1?token=signed.jwt',
        filename: 'diagram-1.png',
        ...extra,
      },
    ]

    it('sin decision previa muestra los tres botones', () => {
      renderMessage('Diagrama', 'assistant', diagram(), vi.fn())

      expect(screen.getByRole('button', { name: '✅ Aprobar' })).toBeInTheDocument()
      expect(screen.getByRole('button', { name: '❌ Rechazar' })).toBeInTheDocument()
      expect(screen.getByRole('button', { name: '✏️ Solicitar cambios' })).toBeInTheDocument()
    })

    it.each([
      ['reject', 'Diagrama rechazado.'],
      ['approve', 'Diagrama aprobado.'],
      ['modify', 'Se registró tu solicitud de cambios.'],
    ] as const)(
      'si el historial trae decision=%s (tras un F5) no vuelve a ofrecer los botones',
      (decision, text) => {
        renderMessage('Diagrama', 'assistant', diagram({ decision }), vi.fn())

        expect(screen.getByText(text)).toBeInTheDocument()
        expect(screen.queryByRole('button', { name: '✅ Aprobar' })).not.toBeInTheDocument()
        expect(screen.queryByRole('button', { name: '❌ Rechazar' })).not.toBeInTheDocument()
        expect(screen.queryByRole('button', { name: '✏️ Solicitar cambios' })).not.toBeInTheDocument()
      }
    )

    it('decision=null se trata como sin decidir', () => {
      renderMessage('Diagrama', 'assistant', diagram({ decision: null }), vi.fn())

      expect(screen.getByRole('button', { name: '❌ Rechazar' })).toBeInTheDocument()
    })

    it('rechazar manda el id del diagrama, muestra la confirmacion y oculta los botones', async () => {
      const user = userEvent.setup()
      renderMessage('Diagrama', 'assistant', diagram(), vi.fn())

      await user.click(screen.getByRole('button', { name: '❌ Rechazar' }))

      await waitFor(() => expect(screen.getByText('Diagrama rechazado.')).toBeInTheDocument())
      expect(submitDecisionMock).toHaveBeenCalledWith(1, 'reject', undefined, 'att-1')
      expect(screen.queryByRole('button', { name: '❌ Rechazar' })).not.toBeInTheDocument()
    })

    it('aprobar manda el id del diagrama', async () => {
      const user = userEvent.setup()
      const onSendMessage = vi.fn()
      renderMessage('Diagrama', 'assistant', diagram(), onSendMessage)

      await user.click(screen.getByRole('button', { name: '✅ Aprobar' }))

      await waitFor(() => expect(onSendMessage).toHaveBeenCalledWith('Apruebo el diagrama, continuemos.'))
      expect(submitDecisionMock).toHaveBeenCalledWith(1, 'approve', undefined, 'att-1')
    })

    it('si el backend falla muestra el error y NO marca el diagrama como decidido', async () => {
      const user = userEvent.setup()
      submitDecisionMock.mockRejectedValueOnce(new Error('Este diagrama ya tiene una decisión registrada.'))
      renderMessage('Diagrama', 'assistant', diagram(), vi.fn())

      await user.click(screen.getByRole('button', { name: '❌ Rechazar' }))

      expect(await screen.findByText('Este diagrama ya tiene una decisión registrada.')).toBeInTheDocument()
      expect(screen.queryByText('Diagrama rechazado.')).not.toBeInTheDocument()
      expect(screen.getByRole('button', { name: '❌ Rechazar' })).toBeInTheDocument()
    })

    it('con dos diagramas en la misma burbuja cada uno tiene su propio estado', () => {
      const two: Attachment[] = [
        ...diagram({ id: 'att-1', decision: 'reject' }),
        ...diagram({ id: 'att-2', url: '/api/chat/attachments/att-2?token=x', decision: null }),
      ]
      renderMessage('Dos diagramas', 'assistant', two, vi.fn())

      expect(screen.getAllByRole('button', { name: '❌ Rechazar' })).toHaveLength(1)
      expect(screen.getByText('Diagrama rechazado.')).toBeInTheDocument()
    })
  })
})
