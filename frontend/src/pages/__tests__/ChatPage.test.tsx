import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('../../api/projects', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/projects')>()
  return {
    ...actual,
    getProject: vi.fn(),
    getProjectPhase: vi.fn(),
    advancePhase: vi.fn(),
  }
})

// Solo interesa la barra de fase: el chat, la elicitación y el historial se reemplazan.
vi.mock('../../components/ChatWindow', () => ({ ChatWindow: () => null }))
vi.mock('../../components/ElicitationPanel', () => ({ ElicitationPanel: () => null }))
vi.mock('../../components/DiagramHistoryPanel', () => ({ DiagramHistoryPanel: () => null }))

import { ChatPage } from '../ChatPage'
import { getProject, getProjectPhase, type PhaseInfo } from '../../api/projects'
import { projectsStore } from '../../stores/projectsStore'

// HU10: cinco fases; la última es `final` (Cierre).
const PHASES = ['requerimientos', 'propuesta', 'refinamiento', 'revision', 'final']

function renderWithPhase(phase: PhaseInfo) {
  vi.mocked(getProject).mockResolvedValue({
    id: 1,
    name: 'demo',
    description: null,
    current_phase: phase.current_phase,
    phase_ready: phase.phase_ready,
    created_at: '2026-09-05T00:00:00Z',
  })
  vi.mocked(getProjectPhase).mockResolvedValue(phase)
  render(
    <MemoryRouter initialEntries={['/projects/1/chat']}>
      <Routes>
        <Route path="/projects/:id/chat" element={<ChatPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('ChatPage — barra de fase (HU10)', () => {
  afterEach(() => {
    vi.clearAllMocks()
    projectsStore.setState({ projects: [], currentProject: null, status: 'idle', error: null })
  })

  it('en la última fase indica que se aprueba en el panel de decisión, sin botones de avance', async () => {
    renderWithPhase({ current_phase: 'final', phase_ready: false, available_phases: PHASES })

    expect(
      await screen.findByText('Última fase: apruébala en el panel de decisión para completar el proyecto.'),
    ).toBeInTheDocument()
    // HU10 (REQ-SA-23): mark-ready se retiró; la decisión vive en <PhaseActions>.
    expect(screen.queryByRole('button', { name: 'Completar proyecto' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Marcar fase como lista' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Avanzar fase/ })).not.toBeInTheDocument()
  })

  it('con la última fase aprobada muestra "Proyecto completado."', async () => {
    renderWithPhase({ current_phase: 'final', phase_ready: true, available_phases: PHASES })

    expect(await screen.findByText('Proyecto completado.')).toBeInTheDocument()
  })

  it('en una fase intermedia sin aprobar no muestra "Marcar fase como lista" ni "Avanzar fase"', async () => {
    renderWithPhase({ current_phase: 'refinamiento', phase_ready: false, available_phases: PHASES })

    expect(await screen.findByText('Fase en progreso.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Marcar fase como lista' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Avanzar fase/ })).not.toBeInTheDocument()
  })

  it('con la fase ya aprobada "Avanzar fase" sale en la barra, no al final del chat', async () => {
    // Antes solo vivía dentro de <PhaseActions>, debajo de todo el chat: en
    // Propuesta quedaba fuera de la vista y había que bajar a buscarlo.
    renderWithPhase({ current_phase: 'propuesta', phase_ready: true, available_phases: PHASES })

    expect(await screen.findByText('Fase lista para avanzar.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Avanzar fase/ })).toBeEnabled()
  })

  it('en requerimientos "Avanzar fase" queda deshabilitado hasta que la fase esté lista', async () => {
    renderWithPhase({ current_phase: 'requerimientos', phase_ready: false, available_phases: PHASES })

    expect(await screen.findByRole('button', { name: /Avanzar fase/ })).toBeDisabled()
  })

  it('sin fases disponibles no se considera última fase', async () => {
    renderWithPhase({ current_phase: 'refinamiento', phase_ready: false, available_phases: [] })

    expect(await screen.findByText('Fase en progreso.')).toBeInTheDocument()
    expect(screen.queryByText('Proyecto completado.')).not.toBeInTheDocument()
  })
})
