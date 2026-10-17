import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../../api/adr', () => ({ getAdr: vi.fn(), generateAdr: vi.fn(), approveAdr: vi.fn() }))
vi.mock('../../api/diagrams', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/diagrams')>()
  return { ...actual, fetchDiagramHistory: vi.fn() }
})

import { AdrPanel, adrFilename, pickAdrDiagram } from '../AdrPanel'
import { approveAdr, generateAdr, getAdr, type AdrOut } from '../../api/adr'
import { fetchDiagramHistory } from '../../api/diagrams'

const EMPTY: AdrOut = { markdown: null, generated_at: null, guide_complete: false, feedback_history: [], approved_at: null }
const ADR: AdrOut = {
  markdown: '# ADR-001: Arquitectura de Clínica\n\n## 1. Contexto\n\nCitas por teléfono',
  generated_at: '2026-10-16T15:00:00+00:00',
  guide_complete: true,
  feedback_history: [],
  approved_at: null,
}

// Muestra a qué ruta navegó el panel y con qué estado.
function ProjectsProbe() {
  const location = useLocation()
  return <p data-testid="projects-page">{JSON.stringify(location.state)}</p>
}

function renderPanel(props: Partial<Parameters<typeof AdrPanel>[0]> = {}) {
  return render(
    <MemoryRouter initialEntries={['/projects/5/chat']}>
      <Routes>
        <Route path="/projects/5/chat" element={<AdrPanel projectId={5} projectName="Clínica" {...props} />} />
        <Route path="/projects" element={<ProjectsProbe />} />
      </Routes>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(fetchDiagramHistory).mockResolvedValue([])
})

describe('AdrPanel', () => {
  it('sin ADR guardado ofrece generarlo', async () => {
    vi.mocked(getAdr).mockResolvedValue(EMPTY)

    renderPanel()

    expect(await screen.findByTestId('adr-empty')).toBeInTheDocument()
    expect(screen.getByTestId('adr-generate')).toHaveTextContent('Generar ADR')
    expect(screen.queryByTestId('adr-download')).not.toBeInTheDocument()
    expect(screen.queryByTestId('adr-approve')).not.toBeInTheDocument()
  })

  it('muestra el ADR guardado con descarga, cambios y aprobación', async () => {
    vi.mocked(getAdr).mockResolvedValue(ADR)

    renderPanel()

    expect(await screen.findByTestId('adr-content')).toHaveTextContent('Citas por teléfono')
    expect(screen.getByTestId('adr-download')).toBeInTheDocument()
    expect(screen.getByTestId('adr-generate')).toHaveTextContent('Regenerar ADR')
    expect(screen.getByTestId('adr-request-changes')).toBeInTheDocument()
    expect(screen.getByTestId('adr-approve')).toHaveTextContent('Aprobar y finalizar proyecto')
  })

  it('genera el ADR al pulsar el botón', async () => {
    vi.mocked(getAdr).mockResolvedValue(EMPTY)
    vi.mocked(generateAdr).mockResolvedValue({ ...ADR, guide_complete: false })

    renderPanel()
    await userEvent.click(await screen.findByTestId('adr-generate'))

    expect(generateAdr).toHaveBeenCalledWith(5, undefined)
    expect(await screen.findByTestId('adr-content')).toBeInTheDocument()
    expect(screen.getByTestId('adr-guide-incomplete')).toBeInTheDocument()
  })

  it('solicitar cambios regenera el ADR con lo pedido', async () => {
    vi.mocked(getAdr).mockResolvedValue(ADR)
    vi.mocked(generateAdr).mockResolvedValue({ ...ADR, feedback_history: ['Usar Redis'] })

    renderPanel()
    await userEvent.click(await screen.findByTestId('adr-request-changes'))
    await userEvent.type(screen.getByLabelText('¿Qué quieres cambiar en el ADR?'), 'Usar Redis')
    await userEvent.click(screen.getByTestId('adr-send-changes'))

    expect(generateAdr).toHaveBeenCalledWith(5, 'Usar Redis')
    await waitFor(() => expect(screen.queryByTestId('adr-changes-form')).not.toBeInTheDocument())
  })

  it('aprobar termina el proyecto, felicita y avisa a la página', async () => {
    vi.mocked(getAdr).mockResolvedValue(ADR)
    vi.mocked(approveAdr).mockResolvedValue({ ...ADR, approved_at: '2026-10-16T16:00:00+00:00' })
    const onCompleted = vi.fn()

    renderPanel({ onCompleted })
    await userEvent.click(await screen.findByTestId('adr-approve'))

    expect(approveAdr).toHaveBeenCalledWith(5)
    expect(await screen.findByTestId('project-completed')).toHaveTextContent('Completaste todas las fases')
    expect(onCompleted).toHaveBeenCalledTimes(1)
    expect(screen.getByTestId('adr-completed')).toBeInTheDocument()
    expect(screen.queryByTestId('adr-approve')).not.toBeInTheDocument()
    expect(screen.queryByTestId('adr-generate')).not.toBeInTheDocument()
  })

  it('"Crear otro proyecto" lleva a Mis proyectos con el diálogo de creación abierto', async () => {
    vi.mocked(getAdr).mockResolvedValue(ADR)
    vi.mocked(approveAdr).mockResolvedValue({ ...ADR, approved_at: '2026-10-16T16:00:00+00:00' })

    renderPanel()
    await userEvent.click(await screen.findByTestId('adr-approve'))
    await userEvent.click(await screen.findByTestId('completed-new-project'))

    expect(await screen.findByTestId('projects-page')).toHaveTextContent('"openCreate":true')
  })

  it('un proyecto ya completado muestra el aviso sin volver a felicitar', async () => {
    vi.mocked(getAdr).mockResolvedValue({ ...ADR, approved_at: '2026-10-16T16:00:00+00:00' })

    renderPanel()

    expect(await screen.findByTestId('adr-completed')).toBeInTheDocument()
    expect(screen.queryByTestId('project-completed')).not.toBeInTheDocument()
  })

  it('muestra el error del backend (p. ej. sin propuesta aprobada)', async () => {
    vi.mocked(getAdr).mockResolvedValue(EMPTY)
    vi.mocked(generateAdr).mockRejectedValue(new Error('Todavía no hay una propuesta aprobada.'))

    renderPanel()
    await userEvent.click(await screen.findByTestId('adr-generate'))

    expect(await screen.findByTestId('adr-error')).toHaveTextContent('propuesta aprobada')
  })

  it('muestra la imagen del diagrama aprobado junto al ADR', async () => {
    vi.mocked(getAdr).mockResolvedValue(ADR)
    vi.mocked(fetchDiagramHistory).mockResolvedValue([
      { message_id: 2, id: 'b', url: '/ultimo.png', filename: null, created_at: '', decision: null },
      { message_id: 1, id: 'a', url: '/aprobado.png', filename: null, created_at: '', decision: 'approve' },
    ])

    renderPanel()

    await waitFor(() => expect(screen.getByTestId('adr-diagram')).toBeInTheDocument())
    expect(screen.getByAltText('Diagrama de la arquitectura del proyecto')).toHaveAttribute('src', '/aprobado.png')
    expect(screen.getByText('Diagrama aprobado')).toBeInTheDocument()
  })

  it('muestra la misma imagen que el diagrama del ADR', async () => {
    vi.mocked(getAdr).mockResolvedValue({ ...ADR, diagram_attachment_id: 'b' })
    vi.mocked(fetchDiagramHistory).mockResolvedValue([
      { message_id: 2, id: 'b', url: '/del-adr.png', filename: null, created_at: '', decision: null },
      { message_id: 1, id: 'a', url: '/aprobado-antes.png', filename: null, created_at: '', decision: 'approve' },
    ])

    renderPanel()

    await waitFor(() => expect(screen.getByTestId('adr-diagram')).toBeInTheDocument())
    expect(screen.getByAltText('Diagrama de la arquitectura del proyecto')).toHaveAttribute('src', '/del-adr.png')
  })

  it('pickAdrDiagram usa el aprobado o el último si el ADR no dice cuál', () => {
    const list = [
      { message_id: 2, id: 'b', url: '/b.png', filename: null, created_at: '', decision: null },
      { message_id: 1, id: 'a', url: '/a.png', filename: null, created_at: '', decision: 'approve' as const },
    ]
    expect(pickAdrDiagram(list, 'b')?.url).toBe('/b.png')
    expect(pickAdrDiagram(list, 'no-existe')?.url).toBe('/a.png')
    expect(pickAdrDiagram(list, null)?.url).toBe('/a.png')
    expect(pickAdrDiagram([], null)).toBeNull()
  })

  it('un ADR aprobado se puede reabrir pidiendo cambios', async () => {
    vi.mocked(getAdr).mockResolvedValue({ ...ADR, approved_at: '2026-10-16T16:00:00+00:00' })
    vi.mocked(generateAdr).mockResolvedValue({ ...ADR, feedback_history: ['Agregar auditoría'] })

    renderPanel()
    await userEvent.click(await screen.findByTestId('adr-reopen'))
    expect(screen.getByTestId('adr-reopen-note')).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText('¿Qué quieres cambiar en el ADR?'), 'Agregar auditoría')
    await userEvent.click(screen.getByTestId('adr-send-changes'))

    expect(generateAdr).toHaveBeenCalledWith(5, 'Agregar auditoría')
    // Reabierto: vuelve a pedir aprobación.
    expect(await screen.findByTestId('adr-approve')).toBeInTheDocument()
    expect(screen.queryByTestId('adr-completed')).not.toBeInTheDocument()
  })

  it('muestra los avisos de la revisión automática de la guía', async () => {
    vi.mocked(getAdr).mockResolvedValue({ ...ADR, guide_warnings: ['Tecnologías en 7.2 que la propuesta aprobada no nombra: Gunicorn'] })

    renderPanel()

    expect(await screen.findByTestId('adr-guide-warnings')).toHaveTextContent('Gunicorn')
  })

  it('arma un nombre de archivo seguro', () => {
    expect(adrFilename('Clínica Médica 2.0')).toBe('ADR-clinica-medica-2-0.md')
    expect(adrFilename(null)).toBe('ADR-proyecto.md')
  })
})
