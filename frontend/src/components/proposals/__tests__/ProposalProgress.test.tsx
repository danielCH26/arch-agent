import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ProposalProgress, formatElapsed } from '../ProposalProgress'
import { proposalsStore } from '../../../stores/proposalsStore'

function setBusy(overrides: Record<string, unknown> = {}) {
  proposalsStore.setState({
    inFlight: 'generating',
    startedAt: Date.now(),
    progress: {
      stage: 'retrieval',
      percent: 12,
      message: 'Buscando patrones de arquitectura relevantes',
      elapsed_ms: 1000,
      budget_s: 300,
    },
    ...overrides,
  })
}

describe('ProposalProgress (F19)', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    proposalsStore.setState({ inFlight: 'idle', progress: null, startedAt: null })
  })
  afterEach(() => {
    // Desmontar ANTES de tocar el store: si no, el setState re-renderiza el
    // componente fuera de act() y React avisa.
    cleanup()
    vi.useRealTimers()
    proposalsStore.setState({ inFlight: 'idle', progress: null, startedAt: null })
  })

  it('no se muestra si no hay una generación en curso', () => {
    const { container } = render(<ProposalProgress />)
    expect(container.firstChild).toBeNull()
  })

  it('muestra etapa, barra accesible con el porcentaje y el tope de tiempo', () => {
    setBusy()
    render(<ProposalProgress />)

    expect(screen.getByTestId('proposal-progress-label')).toHaveTextContent(
      'Buscando patrones de arquitectura relevantes',
    )
    const bar = screen.getByRole('progressbar')
    expect(bar).toHaveAttribute('aria-valuenow', '12')
    expect(bar).toHaveAttribute('aria-valuemin', '0')
    expect(bar).toHaveAttribute('aria-valuemax', '100')
    expect(screen.getByTestId('proposal-progress-time')).toHaveTextContent('12% · 0:00 de ~5:00')
  })

  it('antes del primer evento muestra un estado inicial en 0 %', () => {
    setBusy({ progress: null })
    render(<ProposalProgress />)

    expect(screen.getByTestId('proposal-progress-label')).toHaveTextContent('Iniciando la generación')
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '0')
  })

  it('el cronómetro avanza cada segundo aunque no lleguen eventos', () => {
    setBusy()
    render(<ProposalProgress />)

    act(() => {
      vi.advanceTimersByTime(65_000)
    })

    expect(screen.getByTestId('proposal-progress-time')).toHaveTextContent('1:05')
    expect(screen.queryByTestId('proposal-progress-slow')).toBeNull()
  })

  it('avisa que está tardando después de 2 minutos', () => {
    setBusy()
    render(<ProposalProgress />)

    act(() => {
      vi.advanceTimersByTime(121_000)
    })

    expect(screen.getByTestId('proposal-progress-slow')).toHaveTextContent('tardando más de lo habitual')
  })

  it('el botón Cancelar llama a cancel() del store', () => {
    setBusy()
    const cancel = vi.fn()
    proposalsStore.setState({ cancel })
    render(<ProposalProgress />)

    fireEvent.click(screen.getByTestId('proposal-cancel-generation'))

    expect(cancel).toHaveBeenCalledTimes(1)
  })

  it('también se muestra al modificar y respeta un tope distinto del servidor', () => {
    setBusy({
      inFlight: 'modifying',
      progress: {
        stage: 'generating',
        percent: 55,
        message: 'Redactando la propuesta',
        elapsed_ms: 3000,
        budget_s: 120,
      },
    })
    render(<ProposalProgress />)

    expect(screen.getByTestId('proposal-progress-time')).toHaveTextContent('55% · 0:00 de ~2:00')
  })
})

describe('formatElapsed', () => {
  it('formatea mm:ss y no devuelve negativos', () => {
    expect(formatElapsed(0)).toBe('0:00')
    expect(formatElapsed(65.9)).toBe('1:05')
    expect(formatElapsed(300)).toBe('5:00')
    expect(formatElapsed(-4)).toBe('0:00')
  })
})
