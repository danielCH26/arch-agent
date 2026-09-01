import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { MessageBubble } from '../MessageBubble'
import type { Message } from '../../stores/chatStore'

function renderMessage(content: string, role: Message['role'] = 'assistant') {
  render(<MessageBubble message={{ id: 'message-1', role, content }} />)
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
})
