import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { DiagramHistoryPanel } from '../DiagramHistoryPanel'
import { fetchDiagramHistory, type DiagramVersion } from '../../api/diagrams'
import { fetchDeploymentHistory, type DeploymentVersion } from '../../api/deployments'

vi.mock('../../api/diagrams', () => ({
  fetchDiagramHistory: vi.fn(),
}))

vi.mock('../../api/deployments', () => ({
  fetchDeploymentHistory: vi.fn(),
}))

const fetchMock = vi.mocked(fetchDiagramHistory)
const deployMock = vi.mocked(fetchDeploymentHistory)

const deployment = (over: Partial<DeploymentVersion>): DeploymentVersion => ({
  message_id: 10,
  id: 'dep-1',
  url: '/api/chat/attachments/dep-1?token=x',
  provider: 'aws',
  created_at: '2024-01-02T12:00:00+00:00',
  decision: null,
  ...over,
})

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
    deployMock.mockReset()
    // Por defecto, proyecto sin despliegues: cada prueba que los necesite
    // los declara.
    deployMock.mockResolvedValue([])
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

    expect(await screen.findByText('Aprobado')).toBeInTheDocument()
    expect(screen.getByText('Rechazado')).toBeInTheDocument()
    expect(screen.getByText('Cambios solicitados')).toBeInTheDocument()
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

  it('muestra los diagramas de despliegue en su propia sección', async () => {
    // El panel de Refinamiento desaparece al avanzar: sin esta sección, las
    // versiones del despliegue quedaban inalcanzables desde Revisión.
    fetchMock.mockResolvedValue([version({})])
    deployMock.mockResolvedValue([deployment({ decision: 'approve' })])
    renderPanel()

    expect(await screen.findByTestId('history-deployment')).toBeInTheDocument()
    expect(screen.getByTestId('history-architecture')).toBeInTheDocument()
    expect(screen.getByText('Despliegue en la nube')).toBeInTheDocument()
    expect(screen.getByText(/AWS/)).toBeInTheDocument()
  })

  it('sin despliegues no dibuja esa sección', async () => {
    fetchMock.mockResolvedValue([version({})])
    renderPanel()

    await screen.findByTestId('history-architecture')
    expect(screen.queryByTestId('history-deployment')).not.toBeInTheDocument()
  })

  it('solo despliegues: no dibuja la sección de arquitectura ni el vacío', async () => {
    fetchMock.mockResolvedValue([])
    deployMock.mockResolvedValue([deployment({})])
    renderPanel()

    expect(await screen.findByTestId('history-deployment')).toBeInTheDocument()
    expect(screen.queryByTestId('history-architecture')).not.toBeInTheDocument()
    expect(
      screen.queryByText('Todavía no hay diagramas generados en este proyecto.'),
    ).not.toBeInTheDocument()
  })

  it('si falla el historial de despliegue, los de arquitectura se ven igual', async () => {
    fetchMock.mockResolvedValue([version({})])
    deployMock.mockRejectedValue(new Error('backend viejo'))
    renderPanel()

    expect(await screen.findByTestId('history-architecture')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})
