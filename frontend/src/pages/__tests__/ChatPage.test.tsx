import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('../../api/projects', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/projects')>()
  return {
    ...actual,
    getProject: vi.fn(),
    getProjectPhase: vi.fn(),
    markReady: vi.fn(),
    advancePhase: vi.fn(),
  }
})

// Solo interesa la barra de fase: el chat y el historial se reemplazan.
vi.mock('../../components/ChatWindow', () => ({ ChatWindow: () => null }))
vi.mock('../../components/DiagramHistoryPanel', () => ({ DiagramHistoryPanel: () => null }))

import { ChatPage } from '../ChatPage'
import { getProject, getProjectPhase, type PhaseInfo } from '../../api/projects'
import { projectsStore } from '../../stores/projectsStore'

const PHASES = ['requerimientos', 'propuesta', 'revision']

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

describe('ChatPage — barra de fase', () => {
  afterEach(() => {
    vi.clearAllMocks()
    projectsStore.setState({ projects: [], currentProject: null, status: 'idle', error: null })
  })

  it('en la última fase muestra "Completar proyecto" y oculta "Avanzar fase"', async () => {
    renderWithPhase({ current_phase: 'revision', phase_ready: false, available_phases: PHASES })

    expect(await screen.findByRole('button', { name: 'Completar proyecto' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Avanzar fase/ })).not.toBeInTheDocument()
    expect(screen.getByText('Última fase: usa «Completar proyecto» cuando termines.')).toBeInTheDocument()
  })

  it('con la última fase lista muestra "Proyecto completado."', async () => {
    renderWithPhase({ current_phase: 'revision', phase_ready: true, available_phases: PHASES })

    expect(await screen.findByText('Proyecto completado.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Completar proyecto' })).not.toBeInTheDocument()
  })

  it('en una fase intermedia muestra "Marcar fase como lista" y "Avanzar fase"', async () => {
    renderWithPhase({ current_phase: 'diseno', phase_ready: false, available_phases: ['requerimientos', 'diseno', 'revision'] })

    expect(await screen.findByRole('button', { name: 'Marcar fase como lista' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Avanzar fase/ })).toBeInTheDocument()
  })

  it('sin fases disponibles no se considera última fase', async () => {
    renderWithPhase({ current_phase: 'diseno', phase_ready: false, available_phases: [] })

    expect(await screen.findByRole('button', { name: /Avanzar fase/ })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Completar proyecto' })).not.toBeInTheDocument()
  })
})
