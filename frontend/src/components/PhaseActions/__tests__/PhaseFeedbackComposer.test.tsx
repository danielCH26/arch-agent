import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { PhaseFeedbackComposer } from '../PhaseFeedbackComposer'

const onSubmit = vi.fn()
const onCancel = vi.fn()

beforeEach(() => {
  vi.clearAllMocks()
  onSubmit.mockResolvedValue(undefined)
})

describe('<PhaseFeedbackComposer>', () => {
  it('renders prose-mode (single textarea) for non-revision phases', () => {
    render(
      <PhaseFeedbackComposer
        phase="requerimientos"
        onSubmit={onSubmit}
        onCancel={onCancel}
      />,
    )
    expect(
      screen.getByTestId('phase-feedback-composer-feedback-requerimientos'),
    ).toBeInTheDocument()
    expect(
      screen.queryByTestId('phase-feedback-composer-patron-requerimientos'),
    ).not.toBeInTheDocument()
  })

  it('renders structured fields for revision phase (REQ-SA-7.1)', () => {
    render(
      <PhaseFeedbackComposer
        phase="revision"
        onSubmit={onSubmit}
        onCancel={onCancel}
      />,
    )
    expect(
      screen.getByTestId('phase-feedback-composer-patron-revision'),
    ).toBeInTheDocument()
    expect(
      screen.getByTestId('phase-feedback-composer-ventajas-revision'),
    ).toBeInTheDocument()
    expect(
      screen.getByTestId('phase-feedback-composer-desventajas-revision'),
    ).toBeInTheDocument()
  })

  it('submit fires onSubmit with feedback + payload for revision', async () => {
    render(
      <PhaseFeedbackComposer
        phase="revision"
        initialPayload={{
          patron_elegido: 'Event Sourcing',
          ventajas: ['audit', 'replay'],
          desventajas: ['complexity'],
        }}
        onSubmit={onSubmit}
        onCancel={onCancel}
      />,
    )
    fireEvent.change(
      screen.getByTestId('phase-feedback-composer-feedback-revision'),
      { target: { value: 'switch to event-driven' } },
    )
    fireEvent.click(screen.getByTestId('phase-feedback-composer-submit-revision'))
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1))
    const [feedback, payload] = onSubmit.mock.calls[0]
    expect(feedback).toBe('switch to event-driven')
    expect(payload).toMatchObject({
      patron_elegido: 'Event Sourcing',
      ventajas: ['audit', 'replay'],
      desventajas: ['complexity'],
    })
  })

  it('cancel fires onCancel', () => {
    render(
      <PhaseFeedbackComposer
        phase="requerimientos"
        onSubmit={onSubmit}
        onCancel={onCancel}
      />,
    )
    fireEvent.click(
      screen.getByTestId('phase-feedback-composer-cancel-requerimientos'),
    )
    expect(onCancel).toHaveBeenCalledTimes(1)
  })
})