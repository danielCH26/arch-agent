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
import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'

import { useApprovalsStore } from '../../../stores/approvalsStore'
import { useProjectsStore } from '../../../stores/projectsStore'
import { PhaseActions } from '../PhaseActions'

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
