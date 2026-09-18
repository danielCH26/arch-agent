import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { PhaseHistory } from '../PhaseHistory'
import type { PhaseStatusItem } from '../../../api/approvals'

const onEditMock = vi.fn()

function buildPhaseList(
  currentPhase: 'requerimientos' | 'propuesta' | 'refinamiento' | 'revision' | 'final',
  staleMap: Partial<Record<string, boolean>> = {},
): PhaseStatusItem[] {
  const names: PhaseStatusItem['name'][] = [
    'requerimientos',
    'propuesta',
    'refinamiento',
    'revision',
    'final',
  ]
  return names.map((name) => {
    if (name === currentPhase) {
      return {
        name,
        label: name,
        status: 'active',
        ready: true,
        current_decision: null,
        stale: false,
      }
    }
    return {
      name,
      label: name,
      status: 'approved',
      ready: false,
      current_decision: {
        id: 1,
        action: 'approve',
        feedback: null,
        decided_at: '2026-09-01T00:00:00Z',
      },
      stale: staleMap[name] ?? false,
    }
  })
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('<PhaseHistory>', () => {
  it('renders 5 phase rows', () => {
    render(
      <PhaseHistory
        phases={buildPhaseList('propuesta')}
        currentPhase="propuesta"
        onEdit={onEditMock}
      />,
    )
    expect(screen.getByTestId('phase-history')).toBeInTheDocument()
    expect(screen.getByTestId('phase-history-row-requerimientos')).toBeInTheDocument()
    expect(screen.getByTestId('phase-history-row-propuesta')).toBeInTheDocument()
    expect(screen.getByTestId('phase-history-row-refinamiento')).toBeInTheDocument()
    expect(screen.getByTestId('phase-history-row-revision')).toBeInTheDocument()
    expect(screen.getByTestId('phase-history-row-final')).toBeInTheDocument()
  })

  it('shows skeleton when phases is empty', () => {
    render(
      <PhaseHistory phases={[]} currentPhase={null} onEdit={onEditMock} />,
    )
    expect(screen.getByTestId('phase-history-empty')).toBeInTheDocument()
  })

  it('hides Editar for the active phase', () => {
    render(
      <PhaseHistory
        phases={buildPhaseList('propuesta')}
        currentPhase="propuesta"
        onEdit={onEditMock}
      />,
    )
    expect(screen.queryByTestId('phase-history-edit-propuesta')).not.toBeInTheDocument()
  })

  it('hides Editar for the final phase (REQ-SA-8)', () => {
    render(
      <PhaseHistory
        phases={buildPhaseList('final')}
        currentPhase="final"
        onEdit={onEditMock}
      />,
    )
    expect(screen.queryByTestId('phase-history-edit-final')).not.toBeInTheDocument()
  })

  it('shows Editar for past phases', () => {
    render(
      <PhaseHistory
        phases={buildPhaseList('final')}
        currentPhase="final"
        onEdit={onEditMock}
      />,
    )
    expect(screen.getByTestId('phase-history-edit-requerimientos')).toBeInTheDocument()
    expect(screen.getByTestId('phase-history-edit-propuesta')).toBeInTheDocument()
    expect(screen.getByTestId('phase-history-edit-refinamiento')).toBeInTheDocument()
    expect(screen.getByTestId('phase-history-edit-revision')).toBeInTheDocument()
  })

  it('Editar click triggers onEdit with the phase name', () => {
    render(
      <PhaseHistory
        phases={buildPhaseList('final')}
        currentPhase="final"
        onEdit={onEditMock}
      />,
    )
    fireEvent.click(screen.getByTestId('phase-history-edit-propuesta'))
    expect(onEditMock).toHaveBeenCalledWith('propuesta')
    expect(onEditMock).toHaveBeenCalledTimes(1)
  })

  it('renders yellow stale badge when stale=true (REQ-SA-26)', () => {
    render(
      <PhaseHistory
        phases={buildPhaseList('final', { refinamiento: true, revision: true })}
        currentPhase="final"
        onEdit={onEditMock}
      />,
    )
    expect(screen.getByTestId('phase-history-stale-refinamiento')).toBeInTheDocument()
    expect(screen.getByTestId('phase-history-stale-revision')).toBeInTheDocument()
    expect(
      screen.queryByTestId('phase-history-stale-propuesta'),
    ).not.toBeInTheDocument()
  })

  it('treats stale=undefined as no badge (HU10 backward compat)', () => {
    const phases = buildPhaseList('final', {})
    // Strip the stale field entirely to mimic HU10 responses.
    const stripped = phases.map((p) => ({ ...p, stale: undefined }))
    render(
      <PhaseHistory phases={stripped} currentPhase="final" onEdit={onEditMock} />,
    )
    expect(screen.queryByTestId(/phase-history-stale-/)).not.toBeInTheDocument()
  })

  it('shows last-decision summary per row when current_decision present', () => {
    render(
      <PhaseHistory
        phases={buildPhaseList('final')}
        currentPhase="final"
        onEdit={onEditMock}
      />,
    )
    expect(screen.getByTestId('phase-history-decision-propuesta')).toHaveTextContent(
      /approve/i,
    )
  })

  it('renders status badges per row', () => {
    render(
      <PhaseHistory
        phases={buildPhaseList('propuesta')}
        currentPhase="propuesta"
        onEdit={onEditMock}
      />,
    )
    expect(screen.getByTestId('phase-history-status-active')).toBeInTheDocument()
    const approved = screen.getAllByTestId('phase-history-status-approved')
    expect(approved.length).toBe(4) // 4 non-active phases all approved
  })
})