import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { DiagramHistoryPanel } from '../DiagramHistoryPanel'
import { fetchDiagramHistory, type DiagramVersion } from '../../api/diagrams'

vi.mock('../../api/diagrams', () => ({
  fetchDiagramHistory: vi.fn(),
}))

const fetchMock = vi.mocked(fetchDiagramHistory)

const version = (over: Partial<DiagramVersion>): DiagramVersion => ({
  message_id: 1,
  id: 'att-1',
  url: '/api/chat/attachments/att-1?token=x',
  filename: 'diagram-1.png',
  created_at: '2024-01-01T12:00:00+00:00',
  decision: null,
  ...over,
})

function renderPanel() {
  render(<DiagramHistoryPanel projectId={1} open onClose={() => {}} />)
}

describe('DiagramHistoryPanel (solo lectura)', () => {
  beforeEach(() => {
    fetchMock.mockReset()
  })

  it('no ofrece Aprobar / Rechazar / Pedir cambios: las decisiones se toman en el chat', async () => {
    fetchMock.mockResolvedValue([version({}), version({ id: 'att-2', message_id: 2, decision: 'approve' })])
    renderPanel()

    await screen.findAllByRole('img')

    expect(screen.queryByRole('button', { name: /aprobar/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /rechazar/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /pedir cambios/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
    // el unico boton que queda es el de cerrar el panel
    expect(screen.getAllByRole('button')).toHaveLength(1)
  })

  it('muestra el estado de cada version', async () => {
    fetchMock.mockResolvedValue([
      version({ id: 'a', message_id: 4, decision: 'approve' }),
      version({ id: 'b', message_id: 3, decision: 'reject' }),
      version({ id: 'c', message_id: 2, decision: 'modify' }),
      version({ id: 'd', message_id: 1, decision: null }),
    ])
    renderPanel()

    expect(await screen.findByText('✅ Aprobado')).toBeInTheDocument()
    expect(screen.getByText('❌ Rechazado')).toBeInTheDocument()
    expect(screen.getByText('✏️ Cambios solicitados')).toBeInTheDocument()
    expect(screen.getByText('Sin decisión')).toBeInTheDocument()
  })

  it('proyecto sin diagramas: texto gris, sin error', async () => {
    fetchMock.mockResolvedValue([])
    renderPanel()

    expect(await screen.findByText('Todavía no hay diagramas generados en este proyecto.')).toBeInTheDocument()
  })

  it('error al cargar: mensaje distinto del de lista vacia', async () => {
    fetchMock.mockRejectedValue(new Error('Proyecto no encontrado'))
    renderPanel()

    expect(await screen.findByText('Proyecto no encontrado')).toBeInTheDocument()
    expect(screen.queryByText('Todavía no hay diagramas generados en este proyecto.')).not.toBeInTheDocument()
  })
})
