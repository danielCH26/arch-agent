import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { MessageBubble } from '../MessageBubble'
import type { Attachment, Message } from '../../stores/chatStore'

function renderMessage(
  content: string,
  role: Message['role'] = 'assistant',
  attachments?: Attachment[],
  onSendMessage?: (text: string) => void
) {
  render(
    <MessageBubble
      message={{ id: 'message-1', role, content, attachments }}
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

    expect(onSendMessage).toHaveBeenCalledTimes(1)
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
})
