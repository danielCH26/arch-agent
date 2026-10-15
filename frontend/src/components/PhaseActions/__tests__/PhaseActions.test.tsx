/**
 * PhaseActions mount/render gates (Soomri round-2 re-review, B3).
 *
 * Pins the two render rules that the re-review found broken:
 * 1. The component must render the "Avanzar" button when the phase is
 *    ready (phase_ready=true) even when there is no pending decision --
 *    under the inverted pending_decision semantics (B4 fix), an approved
 *    phase has pending=null, and the old `if (!pending) return null`
 *    unmounted the only surface that can advance the project.
 * 2. When there is neither a pending decision nor a ready phase, the
 *    component renders nothing (REQ-SA-19.2 preserved).
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { advancePhase } from '../../../api/projects'
import { useApprovalsStore } from '../../../stores/approvalsStore'
import { useProjectsStore } from '../../../stores/projectsStore'
import { PhaseActions } from '../PhaseActions'

// Only `advancePhase` is replaced; the rest of the module (used by
// projectsStore) stays real.
vi.mock('../../../api/projects', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../../api/projects')>()),
  advancePhase: vi.fn(),
}))

describe('PhaseActions render gates (B3)', () => {
  beforeEach(() => {
    useApprovalsStore.setState({
      pendingByPhase: {},
      error: null,
    })
    useProjectsStore.setState({
      projects: [],
      currentProject: null,
      status: 'idle',
      error: null,
    })
  })

  it('renders Avanzar when phaseReady=true even without a pending decision', () => {
    render(
      <PhaseActions projectId={7} phase="refinamiento" phaseReady={true} />,
    )

    expect(screen.getByTestId('phase-action-advance')).toBeTruthy()
    // No pending decision: the approve/modify/reject surface stays hidden.
    expect(screen.queryByTestId('phase-action-approve')).toBeNull()
    expect(screen.queryByTestId('phase-action-reject')).toBeNull()
    // And the "Decisión pendiente" header is not shown for an approved phase.
    expect(screen.queryByText(/Decisión pendiente/)).toBeNull()
  })

  it('renders nothing when there is no pending decision and the phase is not ready', () => {
    const { container } = render(
      <PhaseActions projectId={7} phase="refinamiento" phaseReady={false} />,
    )
    expect(container.querySelector('[data-testid="phase-actions"]')).toBeNull()
  })

  it('renders the decision surface when a pending decision exists', () => {
    useApprovalsStore.setState({
      pendingByPhase: {
        refinamiento: {
          phase: 'refinamiento',
          since: '2026-10-07T00:00:00Z',
          last_decision: null,
          last_decided_at: null,
        },
      },
    })
    render(
      <PhaseActions projectId={7} phase="refinamiento" phaseReady={false} />,
    )

    expect(screen.getByTestId('phase-action-approve')).toBeTruthy()
    expect(screen.getByTestId('phase-action-reject')).toBeTruthy()
    // Not ready yet: no advance button (REQ-SA-15).
    expect(screen.queryByTestId('phase-action-advance')).toBeNull()
  })
})

const PENDING_PROPUESTA = {
  propuesta: {
    phase: 'propuesta',
    since: '2026-10-07T00:00:00Z',
    last_decision: null,
    last_decided_at: null,
  },
}

describe('PhaseActions on propuesta (single decision surface)', () => {
  beforeEach(() => {
    useApprovalsStore.setState({ pendingByPhase: {}, error: null })
    useProjectsStore.setState({
      projects: [],
      currentProject: null,
      status: 'idle',
      error: null,
    })
  })

  it('hideDecision keeps only Avanzar: the decision lives in <ProposalCard>', () => {
    useApprovalsStore.setState({ pendingByPhase: PENDING_PROPUESTA })
    render(
      <PhaseActions projectId={7} phase="propuesta" phaseReady={true} hideDecision />,
    )

    expect(screen.getByTestId('phase-action-advance')).toBeTruthy()
    expect(screen.queryByTestId('phase-action-approve')).toBeNull()
    expect(screen.queryByTestId('phase-action-modify')).toBeNull()
    expect(screen.queryByTestId('phase-action-reject')).toBeNull()
    expect(screen.queryByText(/Decisión pendiente/)).toBeNull()
  })

  it('hideDecision renders nothing while the proposal is still undecided', () => {
    useApprovalsStore.setState({ pendingByPhase: PENDING_PROPUESTA })
    const { container } = render(
      <PhaseActions projectId={7} phase="propuesta" phaseReady={false} hideDecision />,
    )
    expect(container.querySelector('[data-testid="phase-actions"]')).toBeNull()
  })
})

describe('PhaseActions Avanzar', () => {
  beforeEach(() => {
    vi.mocked(advancePhase).mockReset()
    useApprovalsStore.setState({ pendingByPhase: {}, error: null })
  })

  it('re-fetches the approvals so the NEW phase gets its pending decision', async () => {
    const refresh = vi.fn().mockResolvedValue(undefined)
    const getProject = vi.fn().mockResolvedValue(null)
    useApprovalsStore.setState({ refresh })
    useProjectsStore.setState({ getProject })
    vi.mocked(advancePhase).mockResolvedValue({
      current_phase: 'revision',
      phase_ready: false,
      message: 'ok',
    })

    render(<PhaseActions projectId={7} phase="refinamiento" phaseReady={true} />)
    fireEvent.click(screen.getByTestId('phase-action-advance'))

    await waitFor(() => expect(refresh).toHaveBeenCalledTimes(1))
    expect(getProject).toHaveBeenCalledWith(7)
  })

  it('shows the failure in the UI instead of only logging it', async () => {
    const refresh = vi.fn().mockResolvedValue(undefined)
    useApprovalsStore.setState({ refresh })
    useProjectsStore.setState({ getProject: vi.fn().mockResolvedValue(null) })
    vi.mocked(advancePhase).mockRejectedValue(
      new Error('La fase actual todavía no está aprobada.'),
    )

    render(<PhaseActions projectId={7} phase="refinamiento" phaseReady={true} />)
    fireEvent.click(screen.getByTestId('phase-action-advance'))

    const alert = await screen.findByTestId('phase-actions-advance-error')
    expect(alert.textContent).toMatch(/todavía no está aprobada/)
    expect(refresh).not.toHaveBeenCalled()
  })
})
