/**
 * HU10 v2 integration test for `useApprovalsStore` reading the real HTTP
 * error body shape (REQ-SA-29, REQ-SA-34).
 *
 * Mocks the network layer at the `apiFetch` boundary (per the existing
 * vitest convention) to return a real FastAPI 409 body and asserts that
 * `useApprovalsStore.decide` surfaces a typed `ApiConflictError` with
 * `current_phase` from `err.data.detail.*` (NOT from `err.data.*`).
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

// Mock the auth store so apiFetch has a token to read.
vi.mock('../../stores/authStore', () => ({
  authStore: {
    getState: () => ({ token: 'test-token', logout: () => {} }),
  },
}))

// Mock the navigation helper.
vi.mock('../../api/navigation', () => ({
  redirectToLogin: () => {},
}))

import { useApprovalsStore } from '../approvalsStore'
import { ApiConflictError } from '../../api/approvals'
import * as clientModule from '../../api/client'

const realApiFetch = clientModule.apiFetch

afterEach(() => {
  vi.restoreAllMocks()
})

describe('approvalsStore integration — typed 409 body (REQ-SA-29)', () => {
  it('reads err.data.detail.* and surfaces ApiConflictError on phase_mismatch', async () => {
    // Real FastAPI 409 body shape (the server wraps typed bodies in `detail`).
    const httpBody = {
      detail: {
        error: 'phase_mismatch',
        current_phase: 'requerimientos',
        requested_phase: 'refinamiento',
      },
    }

    vi.spyOn(clientModule, 'apiFetch').mockImplementation(async () => {
      // Build a real ApiError like the client does on non-2xx responses.
      throw new clientModule.ApiError(
        409,
        (httpBody.detail as Record<string, string>).error ?? 'conflict',
        httpBody,
      )
    })

    const store = useApprovalsStore.getState()
    await expect(
      store.decide(7, 'refinamiento', { action: 'approve' }),
    ).rejects.toBeInstanceOf(ApiConflictError)

    // Re-throw to inspect the typed body.
    let captured: ApiConflictError | null = null
    try {
      await store.decide(7, 'refinamiento', { action: 'approve' })
    } catch (err) {
      captured = err as ApiConflictError
    }
    expect(captured).toBeInstanceOf(ApiConflictError)
    expect(captured!.status).toBe(409)
    expect(captured!.detail.error).toBe('phase_mismatch')
    expect(captured!.currentPhase).toBe('requerimientos')
    expect(captured!.detail.requested_phase).toBe('refinamiento')
  })

  it('tolerates legacy backend shape (err.data.* without detail wrap)', async () => {
    const httpBody = {
      error: 'phase_mismatch',
      current_phase: 'requerimientos',
      requested_phase: 'refinamiento',
    }

    vi.spyOn(clientModule, 'apiFetch').mockImplementation(async () => {
      throw new clientModule.ApiError(409, 'conflict', httpBody)
    })

    const store = useApprovalsStore.getState()
    let captured: ApiConflictError | null = null
    try {
      await store.decide(7, 'refinamiento', { action: 'approve' })
    } catch (err) {
      captured = err as ApiConflictError
    }
    expect(captured).toBeInstanceOf(ApiConflictError)
    expect(captured!.currentPhase).toBe('requerimientos')
  })
})

describe('approvalsStore integration — fetchHistory populates pendingByPhase (REQ-SA-26.1)', () => {
  beforeEach(() => {
    useApprovalsStore.setState({
      pendingByPhase: {},
      historyByPhase: {},
      currentProjectId: null,
      phases: null,
      loading: false,
      error: null,
    })
  })

  it('derives pendingDecision from response.pending_decision', async () => {
    vi.spyOn(clientModule, 'apiFetch').mockResolvedValue({
      phases: [
        { phase: 'requerimientos', label: 'Requerimientos', status: 'approved' },
        { phase: 'propuesta', label: 'Propuesta', status: 'current' },
        { phase: 'refinamiento', label: 'Refinamiento', status: 'pending' },
        { phase: 'revision', label: 'Revisión', status: 'pending' },
        { phase: 'final', label: 'Cierre', status: 'pending' },
      ],
      current_phase: 'propuesta',
      phase_ready: false,
      available_phases: [
        'requerimientos',
        'propuesta',
        'refinamiento',
        'revision',
        'final',
      ],
      pending_decision: {
        phase: 'propuesta',
        since: '2026-09-27T22:00:00Z',
        last_decision: 'approved',
        last_decided_at: '2026-09-27T22:00:00Z',
      },
    })

    const store = useApprovalsStore.getState()
    await store.fetchHistory(7)
    const after = useApprovalsStore.getState()
    expect(after.currentProjectId).toBe(7)
    expect(after.pendingByPhase.propuesta).toEqual({
      phase: 'propuesta',
      since: '2026-09-27T22:00:00Z',
      last_decision: 'approved',
      last_decided_at: '2026-09-27T22:00:00Z',
    })
  })
})

describe('approvalsStore integration — fetchHistory replaces pendingByPhase per project (REQ-SA-27)', () => {
  beforeEach(() => {
    useApprovalsStore.setState({
      pendingByPhase: {},
      historyByPhase: {},
      currentProjectId: null,
      phases: null,
      loading: false,
      error: null,
    })
  })

  it('drops the previous project pending entry when fetching another project (no cross-project leak)', async () => {
    // Project A: pending propuesta (real FastAPI /phases body shape).
    const responseA = {
      phases: [
        { phase: 'requerimientos', label: 'Requerimientos', status: 'approved' },
        { phase: 'propuesta', label: 'Propuesta', status: 'current' },
        { phase: 'refinamiento', label: 'Refinamiento', status: 'pending' },
        { phase: 'revision', label: 'Revisión', status: 'pending' },
        { phase: 'final', label: 'Cierre', status: 'pending' },
      ],
      current_phase: 'propuesta',
      phase_ready: false,
      available_phases: [
        'requerimientos',
        'propuesta',
        'refinamiento',
        'revision',
        'final',
      ],
      pending_decision: {
        phase: 'propuesta',
        since: '2026-09-27T22:00:00Z',
        last_decision: 'approved',
        last_decided_at: '2026-09-27T22:00:00Z',
      },
    }

    // Project B: same phase structure, NO pending decision anywhere —
    // `GET /phases` returns the authoritative map for THIS project.
    const responseB = {
      ...responseA,
      pending_decision: null,
    }

    const spy = vi.spyOn(clientModule, 'apiFetch')
    spy.mockResolvedValueOnce(responseA)
    spy.mockResolvedValueOnce(responseB)

    const store = useApprovalsStore.getState()

    // Project A mounts its pending propuesta entry.
    await store.fetchHistory(1)
    const afterA = useApprovalsStore.getState()
    expect(afterA.currentProjectId).toBe(1)
    expect(afterA.pendingByPhase.propuesta).toEqual(responseA.pending_decision)

    // Switching to project B MUST drop A's stale entry: the fetched
    // response replaces the map (merge would leak A's decision into B
    // and let the user approve a decision B never had).
    await store.fetchHistory(2)
    const afterB = useApprovalsStore.getState()
    expect(afterB.currentProjectId).toBe(2)
    expect(afterB.pendingByPhase).not.toHaveProperty('propuesta')
    expect(Object.keys(afterB.pendingByPhase)).toHaveLength(0)
  })
})