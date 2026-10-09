import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ProposalActions } from '../ProposalActions'
import { proposalsStore } from '../../../stores/proposalsStore'
import * as proposalsApi from '../../../api/proposals'

function resetStore() {
  proposalsStore.setState({
    currentProposal: null,
    iterations: [],
    inFlight: 'idle',
    error: null,
    errorRetryable: false,
    cancelled: false,
    lastModify: null,
  })
}

describe('ProposalActions', () => {
  beforeEach(() => {
    resetStore()
  })
  afterEach(() => {
    vi.restoreAllMocks()
    resetStore()
  })

  it('renders Aprobar / Modificar / Rechazar buttons', () => {
    render(<ProposalActions proposalId={101} />)

    expect(screen.getByTestId('proposal-approve')).toBeInTheDocument()
    expect(screen.getByTestId('proposal-modify')).toBeInTheDocument()
    expect(screen.getByTestId('proposal-reject')).toBeInTheDocument()
  })

  it('dispatches decide("approve") on Aprobar click', async () => {
    const spy = vi
      .spyOn(proposalsApi, 'decideProposal')
      .mockResolvedValue({
        proposal_id: 101,
        lifecycle: 'approved',
        current_phase: 'propuesta',
        phase_ready: true,
      })

    render(<ProposalActions proposalId={101} />)

    fireEvent.click(screen.getByTestId('proposal-approve'))

    await waitFor(() => {
      expect(spy).toHaveBeenCalledWith(101, 'approve', undefined)
    })
  })

  it('dispatches decide("reject") on Rechazar click with optional comment', async () => {
    const spy = vi
      .spyOn(proposalsApi, 'decideProposal')
      .mockResolvedValue({
        proposal_id: 101,
        lifecycle: 'rejected',
        current_phase: 'requerimientos',
        phase_ready: false,
      })

    render(<ProposalActions proposalId={101} />)

    fireEvent.change(screen.getByTestId('proposal-comment'), {
      target: { value: 'falta detalle' },
    })
    fireEvent.click(screen.getByTestId('proposal-reject'))

    await waitFor(() => {
      expect(spy).toHaveBeenCalledWith(101, 'reject', 'falta detalle')
    })
  })

  it('opens the composer on Modificar click and only fires modify() with non-empty feedback', async () => {
    // modify() opens an SSE stream; we stub it so the test doesn't hang.
    const modifySpy = vi
      .spyOn(proposalsApi, 'createProposalStream')
      .mockImplementation((endpoint, _payload, callbacks) => {
        // emit a sources event, then done immediately so the store transitions
        // cleanly back to idle for the next assertion
        callbacks.onSources([])
        callbacks.onDone(200, [])
        return () => {}
      })

    render(<ProposalActions proposalId={101} />)

    fireEvent.click(screen.getByTestId('proposal-modify'))
    expect(screen.getByTestId('proposal-composer')).toBeInTheDocument()

    // Empty feedback blocks the submit button to fire
    fireEvent.click(screen.getByTestId('proposal-submit-feedback'))
    expect(modifySpy).not.toHaveBeenCalled()
    expect(
      screen.getByTestId('proposal-actions-error'),
    ).toHaveTextContent(/feedback antes de iterar/i)

    fireEvent.change(screen.getByTestId('proposal-feedback'), {
      target: { value: 'agregar cache' },
    })
    fireEvent.click(screen.getByTestId('proposal-submit-feedback'))

    await waitFor(() => {
      expect(modifySpy).toHaveBeenCalledWith(
        'modify',
        expect.objectContaining({ feedback: 'agregar cache' }),
        expect.anything(),
      )
    })
  })

  it('disables all buttons when `disabled` is true', () => {
    render(<ProposalActions proposalId={101} disabled />)

    expect(screen.getByTestId('proposal-approve')).toBeDisabled()
    expect(screen.getByTestId('proposal-modify')).toBeDisabled()
    expect(screen.getByTestId('proposal-reject')).toBeDisabled()
  })

  it('tras un fallo de la modificación ofrece reintentar con el mismo feedback', () => {
    const retry = vi.fn()
    proposalsStore.setState({
      error: 'La generación superó el tiempo máximo (5 min)',
      errorRetryable: true,
      lastModify: { proposalId: 101, feedback: 'agrega caché' },
      retry,
    })
    render(<ProposalActions proposalId={101} />)

    expect(screen.getByTestId('proposal-retry-feedback')).toHaveTextContent('agrega caché')
    fireEvent.click(screen.getByTestId('proposal-retry'))

    expect(retry).toHaveBeenCalledTimes(1)
  })

  it('no ofrece reintentar si no hay error ni cancelación, o mientras se genera', () => {
    proposalsStore.setState({ error: null, cancelled: false, lastModify: { proposalId: 101, feedback: 'x' } })
    const { rerender } = render(<ProposalActions proposalId={101} />)
    expect(screen.queryByTestId('proposal-retry')).toBeNull()

    proposalsStore.setState({ error: 'boom', inFlight: 'modifying' })
    rerender(<ProposalActions proposalId={101} />)
    expect(screen.queryByTestId('proposal-retry')).toBeNull()
  })

  it('no ofrece reintentar ante un error permanente', () => {
    proposalsStore.setState({
      error: 'Has alcanzado el máximo de iteraciones (5)',
      errorRetryable: false,
      cancelled: false,
      lastModify: { proposalId: 101, feedback: 'x' },
    })
    render(<ProposalActions proposalId={101} />)

    expect(screen.queryByTestId('proposal-retry')).toBeNull()
  })

  it('el reintento lo decide `retryable`, no la redacción del mensaje', () => {
    // Texto que el antiguo regex habría tomado por reintentable ("tiempo máximo",
    // "timed out", "stream failed") pero que el backend marcó como permanente.
    for (const error of ['Superó el tiempo máximo', 'request timed out', 'SSE stream failed']) {
      proposalsStore.setState({
        error,
        errorRetryable: false,
        cancelled: false,
        lastModify: { proposalId: 101, feedback: 'x' },
      })
      const { unmount } = render(<ProposalActions proposalId={101} />)
      expect(screen.queryByTestId('proposal-retry')).toBeNull()
      unmount()
    }
  })

  it('ofrece reintentar ante un error marcado reintentable aunque el texto no diga nada típico', () => {
    proposalsStore.setState({
      error: 'Mensaje con otra redacción',
      errorRetryable: true,
      cancelled: false,
      lastModify: { proposalId: 101, feedback: 'x' },
    })
    render(<ProposalActions proposalId={101} />)

    expect(screen.getByTestId('proposal-retry')).toBeInTheDocument()
  })

  it('un flag reintentable huérfano (sin error) no muestra el reintento', () => {
    proposalsStore.setState({
      error: null,
      errorRetryable: true,
      cancelled: false,
      lastModify: { proposalId: 101, feedback: 'x' },
    })
    render(<ProposalActions proposalId={101} />)

    expect(screen.queryByTestId('proposal-retry')).toBeNull()
  })

  it('tras cancelar una modificación también se puede reintentar', () => {
    proposalsStore.setState({
      error: null,
      cancelled: true,
      lastModify: { proposalId: 101, feedback: 'agrega caché' },
    })
    render(<ProposalActions proposalId={101} />)

    expect(screen.getByTestId('proposal-retry')).toBeInTheDocument()
  })
})

describe('ProposalActions: reintento solo para la propuesta vigente (review PR)', () => {
  beforeEach(() => resetStore())
  afterEach(() => resetStore())

  it('no ofrece reintentar si el feedback pendiente es de otra propuesta (id viejo)', () => {
    proposalsStore.setState({
      error: 'La generación superó el tiempo máximo (5 min)',
      errorRetryable: true,
      lastModify: { proposalId: 101, feedback: 'agrega caché' },
    })
    // La vigente ya es la 102: reintentar con 101 daría 409.
    render(<ProposalActions proposalId={102} />)

    expect(screen.queryByTestId('proposal-retry')).toBeNull()
  })

  it('tras cancelar también exige que sea la misma propuesta', () => {
    proposalsStore.setState({
      cancelled: true,
      lastModify: { proposalId: 101, feedback: 'x' },
    })
    render(<ProposalActions proposalId={103} />)

    expect(screen.queryByTestId('proposal-retry')).toBeNull()
  })
})
