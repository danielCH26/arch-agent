import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { Layout } from '../Layout'
import { projectsStore } from '../../stores/projectsStore'

function renderLayout() {
  render(
    <MemoryRouter initialEntries={['/projects/1/chat']}>
      <Routes>
        <Route element={<Layout />}>
          <Route path="projects/:id/chat" element={<p>Chat del proyecto</p>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  )
}

describe('Layout', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    projectsStore.setState({ projects: [], status: 'idle', error: null })
  })

  it('opens the creation dialog from the sidebar without navigating to the dashboard', () => {
    projectsStore.setState({
      projects: [],
      status: 'idle',
      error: null,
      fetchProjects: vi.fn().mockResolvedValue(undefined),
    })

    renderLayout()
    fireEvent.click(screen.getByRole('button', { name: /nuevo proyecto/i }))

    expect(screen.getByRole('heading', { name: 'Nuevo Proyecto' })).toBeInTheDocument()
    expect(screen.getByText('Chat del proyecto')).toBeInTheDocument()
  })
})
