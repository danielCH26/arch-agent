import { beforeEach, describe, expect, it, vi } from 'vitest'

// Mock the API module BEFORE importing the store.
vi.mock('../../api/approvals', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/approvals')>()
  return {
    ...actual,
    decidePhase: vi.fn(),
    listPhases: vi.fn(),
  }
})

import {
  PhaseDecisionConflict,
  type DecisionResponse,
  type Phase,
  type PhaseListResponse,
  decidePhase,
  listPhases,
} from '../../api/approvals'
import { approvalsStore } from '../approvalsStore'

const decidePhaseMock = vi.mocked(decidePhase)
const listPhasesMock = vi.mocked(listPhases)

const PROJECT_ID = '1'

function _phaseListResponse(
  currentPhase: Phase,
  approved: Phase[] = [],
): PhaseListResponse {
  const phases: PhaseListResponse['phases'] = (
    ['requerimientos', 'propuesta', 'refinamiento', 'revision', 'final'] as Phase[]
  ).map((name) => {
    if (name === currentPhase) {
      return {
        name,
        label: name,
        status: 'active' as const,
        ready: false,
        current_decision: null,
      }
    }
    if (approved.includes(name)) {
      return {
        name,
        label: name,
        status: 'approved' as const,
        ready: false,
        current_decision: {
          id: 1,
          action: 'approve',
          feedback: null,
          decided_at: '2026-01-01T00:00:00Z',
        },
      }
    }
    return {
      name,
      label: name,
      status: 'pending' as const,
      ready: false,
      current_decision: null,
    }
  })
  return { phases, current_phase: currentPhase }
}

describe('approvalsStore', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    approvalsStore.getState().reset()
  })

  it('starts with empty pending + history for all 5 phases (REQ-SA-21)', () => {
    const state = approvalsStore.getState()
    for (const phase of [
      'requerimientos',
      'propuesta',
      'refinamiento',
      'revision',
      'final',
    ] as Phase[]) {
      expect(state.pendingDecision[phase]).toBeNull()
      expect(state.historyByPhase[phase]).toEqual([])
    }
  })

  it('fetchHistory populates phases + historyByPhase (REQ-SA-21)', async () => {
    listPhasesMock.mockResolvedValue(
      _phaseListResponse('propuesta', ['requerimientos']),
    )
    await approvalsStore.getState().fetchHistory(PROJECT_ID)
    const state = approvalsStore.getState()
    expect(state.currentPhase).toBe('propuesta')
    expect(state.phases.length).toBe(5)
    expect(state.historyByPhase.requerimientos.length).toBe(1)
    expect(state.historyByPhase.requerimientos[0].action).toBe('approve')
    expect(state.historyByPhase.propuesta).toEqual([])
  })

  it('decide() sends POST to the generic endpoint (REQ-SA-22)', async () => {
    listPhasesMock.mockResolvedValue(_phaseListResponse('propuesta'))
    const fakeResponse: DecisionResponse = {
      decision_id: 99,
      project_id: 1,
      phase: 'propuesta',
      action: 'approve',
      next_phase: 'refinamiento',
      decided_at: '2026-01-01T00:00:00Z',
      idempotent: false,
    }
    decidePhaseMock.mockResolvedValue(fakeResponse)

    const result = await approvalsStore
      .getState()
      .decide(PROJECT_ID, 'propuesta', { action: 'approve' })

    expect(decidePhaseMock).toHaveBeenCalledWith(PROJECT_ID, 'propuesta', {
      action: 'approve',
    })
    expect(result).toEqual(fakeResponse)
    // The pending slot clears after a successful decide.
    expect(approvalsStore.getState().pendingDecision.propuesta).toBeNull()
  })

  it('decide() prepends the optimistic decision to history (REQ-SA-21.1)', async () => {
    // Mock the post-decide fetchHistory to include the new decision in
    // current_decision so the assertion holds after re-sync.
    listPhasesMock.mockResolvedValue(
      _phaseListResponse('refinamiento').phases.map((p) =>
        p.name === 'refinamiento'
          ? {
              ...p,
              status: 'approved' as const,
              current_decision: {
                id: 42,
                action: 'approve',
                feedback: null,
                decided_at: '2026-01-01T12:00:00Z',
              },
            }
          : p,
      ) as unknown as PhaseListResponse,
    )
    const fakeResponse: DecisionResponse = {
      decision_id: 42,
      project_id: 1,
      phase: 'refinamiento',
      action: 'approve',
      next_phase: 'revision',
      decided_at: '2026-01-01T12:00:00Z',
      idempotent: false,
    }
    decidePhaseMock.mockResolvedValue(fakeResponse)

    await approvalsStore
      .getState()
      .decide(PROJECT_ID, 'refinamiento', { action: 'approve' })

    const state = approvalsStore.getState()
    expect(state.historyByPhase.refinamiento[0].id).toBe(42)
    expect(state.historyByPhase.refinamiento[0].action).toBe('approve')
  })

  it('decide() 409 re-syncs history without crashing (REQ-SA-9)', async () => {
    listPhasesMock.mockResolvedValue(
      _phaseListResponse('requerimientos', ['requerimientos']),
    )
    decidePhaseMock.mockRejectedValue(
      new PhaseDecisionConflict('approve', '2026-01-01T00:00:00Z'),
    )

    await expect(
      approvalsStore.getState().decide(PROJECT_ID, 'requerimientos', {
        action: 'reject',
      }),
    ).rejects.toBeInstanceOf(PhaseDecisionConflict)

    // listPhases was called exactly once -- the 409 re-sync path -- because
    // no initial fetchHistory() ran before the decide().
    expect(listPhasesMock).toHaveBeenCalledTimes(1)
    // pendingPhase was cleared even on the conflict path so the UI can
    // render the current decision instead of being stuck on 'pending'.
    expect(approvalsStore.getState().pendingDecision.requerimientos).toBeNull()
    expect(approvalsStore.getState().error).toMatch(/Conflicto/)
  })

  it('setPending marks a phase as needing a decision', () => {
    approvalsStore.getState().setPending('revision')
    expect(approvalsStore.getState().pendingDecision.revision).toEqual({
      phase: 'revision',
    })
  })

  it('clearPending resets the slot', () => {
    approvalsStore.getState().setPending('final')
    approvalsStore.getState().clearPending('final')
    expect(approvalsStore.getState().pendingDecision.final).toBeNull()
  })

  it('reset clears all state', async () => {
    listPhasesMock.mockResolvedValue(_phaseListResponse('propuesta'))
    await approvalsStore.getState().fetchHistory(PROJECT_ID)
    approvalsStore.getState().reset()
    const state = approvalsStore.getState()
    expect(state.phases).toEqual([])
    expect(state.currentPhase).toBeNull()
    expect(state.error).toBeNull()
    expect(state.historyByPhase.propuesta).toEqual([])
  })
})