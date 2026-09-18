import { beforeEach, describe, expect, it, vi } from 'vitest'

// Mock the API module BEFORE importing the store.
vi.mock('../../api/approvals', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/approvals')>()
  return {
    ...actual,
    decidePhase: vi.fn(),
    listPhases: vi.fn(),
    createRegenerateStream: vi.fn(),
  }
})

import {
  PhaseDecisionConflict,
  type DecisionResponse,
  type Phase,
  type PhaseListResponse,
  createRegenerateStream,
  decidePhase,
  listPhases,
} from '../../api/approvals'
import { approvalsStore } from '../approvalsStore'

const decidePhaseMock = vi.mocked(decidePhase)
const listPhasesMock = vi.mocked(listPhases)
const createRegenerateStreamMock = vi.mocked(createRegenerateStream)

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

  // HU11 (REQ-SA-25): regeneratePhase action + AbortController cleanup.
})

describe('approvalsStore — regeneratePhase (HU11 REQ-SA-25)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    approvalsStore.getState().reset()
    listPhasesMock.mockResolvedValue(_phaseListResponse('final'))
  })

  it('starts idle with regeneratingPhase=null', () => {
    expect(approvalsStore.getState().regeneratingPhase).toBeNull()
  })

  it('calls createRegenerateStream with phase + feedback (REQ-SA-25)', async () => {
    let onDone: ((payload: Record<string, unknown>) => void) | undefined
    createRegenerateStreamMock.mockImplementation(
      (
        _projectId,
        phase,
        body,
        callbacks: {
          onDone?: (payload: Record<string, unknown>) => void
        },
      ) => {
        expect(phase).toBe('propuesta')
        expect(body.feedback).toBe('add caching')
        onDone = callbacks.onDone
        return () => undefined
      },
    )

    const promise = approvalsStore
      .getState()
      .regeneratePhase(PROJECT_ID, 'propuesta', { feedback: 'add caching' })

    // The store sets regeneratingPhase immediately.
    expect(approvalsStore.getState().regeneratingPhase).toBe('propuesta')

    // Fire the done callback to resolve the promise.
    onDone?.({ proposal_id: 99, iteration: 3 })
    await promise

    expect(approvalsStore.getState().regeneratingPhase).toBeNull()
  })

  it('re-syncs history on done', async () => {
    let onDone: ((payload: Record<string, unknown>) => void) | undefined
    createRegenerateStreamMock.mockImplementation(
      (_id, _phase, _body, callbacks) => {
        onDone = callbacks.onDone
        return () => undefined
      },
    )

    const promise = approvalsStore
      .getState()
      .regeneratePhase(PROJECT_ID, 'propuesta', { feedback: 'x' })

    onDone?.({})
    await promise

    // listPhases called at least once (the re-sync after done).
    expect(listPhasesMock).toHaveBeenCalled()
  })

  it('error event clears regeneratingPhase + sets error (REQ-SA-25.4)', async () => {
    let onError: ((message: string) => void) | undefined
    createRegenerateStreamMock.mockImplementation(
      (_id, _phase, _body, callbacks) => {
        onError = callbacks.onError
        return () => undefined
      },
    )

    const promise = approvalsStore
      .getState()
      .regeneratePhase(PROJECT_ID, 'propuesta', { feedback: 'x' })

    onError?.('LLM unavailable')
    await promise

    const state = approvalsStore.getState()
    expect(state.regeneratingPhase).toBeNull()
    expect(state.error).toMatch(/Regenerate failed/)
    expect(state.error).toMatch(/LLM unavailable/)
  })

  it('error path keeps the prior decision audit row (REQ-SA-25.4)', async () => {
    // The store does NOT call decide() again or roll back history on
    // regenerate failure — only the audit row stays. Verify by checking
    // historyByPhase is unchanged after a failed regenerate.
    const initial = _phaseListResponse('propuesta', ['requerimientos'])
    listPhasesMock.mockResolvedValue(initial)
    await approvalsStore.getState().fetchHistory(PROJECT_ID)

    const historyBefore = approvalsStore.getState().historyByPhase.requerimientos
    expect(historyBefore.length).toBe(1)

    let onError: ((message: string) => void) | undefined
    createRegenerateStreamMock.mockImplementation(
      (_id, _phase, _body, callbacks) => {
        onError = callbacks.onError
        return () => undefined
      },
    )
    const promise = approvalsStore
      .getState()
      .regeneratePhase(PROJECT_ID, 'requerimientos', { feedback: 'x' })
    onError?.('boom')
    await promise

    // The audit row is still in historyByPhase — store never called decide().
    expect(decidePhaseMock).not.toHaveBeenCalled()
    expect(
      approvalsStore.getState().historyByPhase.requerimientos.length,
    ).toBe(1)
  })

  it('reset clears regeneratingPhase', async () => {
    let onDone: ((payload: Record<string, unknown>) => void) | undefined
    createRegenerateStreamMock.mockImplementation(
      (_id, _phase, _body, callbacks) => {
        onDone = callbacks.onDone
        return () => undefined
      },
    )
    const promise = approvalsStore
      .getState()
      .regeneratePhase(PROJECT_ID, 'propuesta', { feedback: 'x' })
    onDone?.({})
    await promise
    approvalsStore.getState().reset()
    expect(approvalsStore.getState().regeneratingPhase).toBeNull()
  })
})