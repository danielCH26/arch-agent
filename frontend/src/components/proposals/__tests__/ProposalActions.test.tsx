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
})