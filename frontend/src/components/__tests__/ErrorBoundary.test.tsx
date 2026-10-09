import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ErrorBoundary } from '../ErrorBoundary'

let shouldThrow = true

function Flaky() {
  if (shouldThrow) throw new Error('fallo de render')
  return <p>Contenido listo</p>
}

describe('ErrorBoundary', () => {
  beforeEach(() => {
    shouldThrow = true
    // React registra el error atrapado en consola; se silencia en el test.
    vi.spyOn(console, 'error').mockImplementation(() => {})
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('muestra un mensaje en vez de dejar la pantalla en blanco', () => {
    render(
      <ErrorBoundary>
        <Flaky />
      </ErrorBoundary>,
    )
    expect(screen.getByRole('alert')).toHaveTextContent('Algo salió mal')
    expect(screen.getByRole('link', { name: 'Ir a mis proyectos' })).toHaveAttribute('href', '/projects')
  })

  it('"Intentar de nuevo" vuelve a renderizar el contenido', () => {
    render(
      <ErrorBoundary>
        <Flaky />
      </ErrorBoundary>,
    )
    shouldThrow = false
    fireEvent.click(screen.getByRole('button', { name: 'Intentar de nuevo' }))
    expect(screen.getByText('Contenido listo')).toBeInTheDocument()
  })

  it('se reinicia al cambiar resetKey (p. ej. al navegar)', () => {
    const { rerender } = render(
      <ErrorBoundary resetKey="/a">
        <Flaky />
      </ErrorBoundary>,
    )
    expect(screen.getByText('Algo salió mal')).toBeInTheDocument()

    shouldThrow = false
    rerender(
      <ErrorBoundary resetKey="/b">
        <Flaky />
      </ErrorBoundary>,
    )
    expect(screen.getByText('Contenido listo')).toBeInTheDocument()
  })
})
