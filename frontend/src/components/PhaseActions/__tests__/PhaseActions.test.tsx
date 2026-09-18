import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { PhaseActions } from '../PhaseActions'
import type { Decision } from '../../../api/approvals'

const onApprove = vi.fn()
const onModify = vi.fn()
const onReject = vi.fn()

beforeEach(() => {
  vi.clearAllMocks()
  onApprove.mockResolvedValue(undefined)
  onModify.mockResolvedValue(undefined)
  onReject.mockResolvedValue(undefined)
})

describe('<PhaseActions>', () => {
  it('renders 3 buttons (Aprobar / Modificar / Rechazar) for prose phases (REQ-SA-1)', () => {
    render(
      <PhaseActions
        phase="propuesta"
        currentDecision={null}
        onApprove={onApprove}
        onModify={onModify}
        onReject={onReject}
      />,
    )
    expect(screen.getByTestId('phase-actions-approve-propuesta')).toBeInTheDocument()
    expect(screen.getByTestId('phase-actions-modify-propuesta')).toBeInTheDocument()
    expect(screen.getByTestId('phase-actions-reject-propuesta')).toBeInTheDocument()
  })

  it('does NOT render Modificar on the final phase (REQ-SA-8.1)', () => {
    render(
      <PhaseActions
        phase="final"
        currentDecision={null}
        onApprove={onApprove}
        onModify={onModify}
        onReject={onReject}
      />,
    )
    expect(screen.getByTestId('phase-actions-approve-final')).toBeInTheDocument()
    expect(screen.getByTestId('phase-actions-reject-final')).toBeInTheDocument()
    expect(screen.queryByTestId('phase-actions-modify-final')).not.toBeInTheDocument()
  })

  it('Aprobar click fires onApprove (REQ-SA-20.1)', async () => {
    render(
      <PhaseActions
        phase="requerimientos"
        currentDecision={null}
        onApprove={onApprove}
        onModify={onModify}
        onReject={onReject}
      />,
    )
    fireEvent.click(screen.getByTestId('phase-actions-approve-requerimientos'))
    await waitFor(() => expect(onApprove).toHaveBeenCalledTimes(1))
  })

  it('Modificar click opens the PhaseFeedbackComposer', async () => {
    render(
      <PhaseActions
        phase="revision"
        currentDecision={null}
        onApprove={onApprove}
        onModify={onModify}
        onReject={onReject}
      />,
    )
    fireEvent.click(screen.getByTestId('phase-actions-modify-revision'))
    await waitFor(() =>
      expect(
        screen.getByTestId('phase-feedback-composer-revision'),
      ).toBeInTheDocument(),
    )
  })

  it('shows current decision summary when provided', () => {
    const decision: Decision = {
      id: 1,
      action: 'approve',
      decided_at: '2026-01-01T00:00:00Z',
    }
    render(
      <PhaseActions
        phase="propuesta"
        currentDecision={decision}
        onApprove={onApprove}
        onModify={onModify}
        onReject={onReject}
      />,
    )
    expect(
      screen.getByTestId('phase-actions-decision-propuesta'),
    ).toHaveTextContent(/approve/i)
  })

  // HU11 (REQ-SA-25 / T8): past-mode variant.
})

describe('<PhaseActions mode="past">', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    onApprove.mockResolvedValue(undefined)
    onModify.mockResolvedValue(undefined)
    onReject.mockResolvedValue(undefined)
  })

  it('hides Aprobar and Rechazar in past mode (REQ-SA-25 / design §F.1)', () => {
    render(
      <PhaseActions
        phase="propuesta"
        mode="past"
        currentPhase="refinamiento"
        currentDecision={null}
        onApprove={onApprove}
        onModify={onModify}
        onReject={onReject}
      />,
    )
    expect(
      screen.queryByTestId('phase-actions-approve-propuesta'),
    ).not.toBeInTheDocument()
    expect(
      screen.queryByTestId('phase-actions-reject-propuesta'),
    ).not.toBeInTheDocument()
    expect(screen.getByTestId('phase-actions-modify-propuesta')).toBeInTheDocument()
  })

  it('shows past-mode banner referencing currentPhase', () => {
    render(
      <PhaseActions
        phase="requerimientos"
        mode="past"
        currentPhase="refinamiento"
        currentDecision={null}
        onApprove={onApprove}
        onModify={onModify}
        onReject={onReject}
      />,
    )
    const banner = screen.getByTestId('phase-actions-past-banner-requerimientos')
    expect(banner).toBeInTheDocument()
    expect(banner).toHaveTextContent(/refinamiento/)
    expect(banner).toHaveTextContent(/anterior/i)
  })

  it('exposes data-phase-mode="past" on root', () => {
    const { container } = render(
      <PhaseActions
        phase="propuesta"
        mode="past"
        currentPhase="final"
        currentDecision={null}
        onApprove={onApprove}
        onModify={onModify}
        onReject={onReject}
      />,
    )
    const root = container.querySelector('[data-phase-mode="past"]')
    expect(root).toBeInTheDocument()
  })

  it('relabels the modify button to "Regenerar" in past mode', () => {
    render(
      <PhaseActions
        phase="propuesta"
        mode="past"
        currentPhase="refinamiento"
        currentDecision={null}
        onApprove={onApprove}
        onModify={onModify}
        onReject={onReject}
      />,
    )
    expect(screen.getByTestId('phase-actions-modify-propuesta')).toHaveTextContent(
      /Regenerar/,
    )
  })

  it('Modificar (now "Regenerar") click still opens the PhaseFeedbackComposer', async () => {
    render(
      <PhaseActions
        phase="propuesta"
        mode="past"
        currentPhase="refinamiento"
        currentDecision={null}
        onApprove={onApprove}
        onModify={onModify}
        onReject={onReject}
      />,
    )
    fireEvent.click(screen.getByTestId('phase-actions-modify-propuesta'))
    await waitFor(() =>
      expect(
        screen.getByTestId('phase-feedback-composer-propuesta'),
      ).toBeInTheDocument(),
    )
  })

  it('does NOT render Aprobar/Rechazar for past mode even on revision phase', () => {
    render(
      <PhaseActions
        phase="revision"
        mode="past"
        currentPhase="final"
        currentDecision={null}
        onApprove={onApprove}
        onModify={onModify}
        onReject={onReject}
      />,
    )
    expect(
      screen.queryByTestId('phase-actions-approve-revision'),
    ).not.toBeInTheDocument()
    expect(
      screen.queryByTestId('phase-actions-reject-revision'),
    ).not.toBeInTheDocument()
    expect(screen.getByTestId('phase-actions-modify-revision')).toBeInTheDocument()
  })

  it('default mode preserves HU10 button layout (regression guard)', () => {
    render(
      <PhaseActions
        phase="propuesta"
        currentDecision={null}
        onApprove={onApprove}
        onModify={onModify}
        onReject={onReject}
      />,
    )
    expect(screen.getByTestId('phase-actions-approve-propuesta')).toBeInTheDocument()
    expect(screen.getByTestId('phase-actions-modify-propuesta')).toHaveTextContent(
      /Modificar/,
    )
    expect(screen.getByTestId('phase-actions-reject-propuesta')).toBeInTheDocument()
  })
})