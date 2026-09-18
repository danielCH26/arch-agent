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
})