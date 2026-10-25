import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

vi.mock('../../stores/projectsStore', () => {
  const state = { projects: [], error: null, hasLoaded: true, fetchProjects: vi.fn() }
  const store = Object.assign(() => state, { getState: () => state })
  return { projectsStore: store }
})

import { ProjectsPage } from '../ProjectsPage'

function StateProbe() {
  const location = useLocation()
  return <pre data-testid="state">{JSON.stringify(location.state)}</pre>
}

describe('ProjectsPage', () => {
  it('muestra el aviso de la redirección una sola vez y lo quita del historial', async () => {
    render(
      <MemoryRouter initialEntries={[{ pathname: '/projects', state: { message: 'Ese proyecto ya no está disponible' } }]}>
        <Routes>
          <Route
            path="/projects"
            element={
              <>
                <ProjectsPage />
                <StateProbe />
              </>
            }
          />
        </Routes>
      </MemoryRouter>,
    )

    // El aviso se ve…
    expect(screen.getByRole('status')).toHaveTextContent('Ese proyecto ya no está disponible')
    // …pero ya no queda en el estado del historial: duplicar la pestaña o
    // recargar no lo vuelve a mostrar.
    await waitFor(() => expect(screen.getByTestId('state')).toHaveTextContent('null'))
    expect(screen.getByRole('status')).toHaveTextContent('Ese proyecto ya no está disponible')
  })
})
