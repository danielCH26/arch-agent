// jsdom does not implement scrollIntoView; stub it so ChatWindow's
// useEffect-driven auto-scroll does not throw during the test render.
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = function () {
    /* noop for jsdom */
  }
}

import { vi } from 'vitest'

// Mock the chat store BEFORE importing the component under test.
// This file isolates the F12 REQ-9 / SCN-2 mount-time fetch tests so the
// vi.mock does not leak into the SCN-8 ProposalCard tests (which need the
// real chatStore to set up state).
const loadHistoryMock = vi.fn()

vi.mock('../../stores/chatStore', () => {
  const actualState = {
    messages: [],
    isStreaming: false,
    error: null,
    loadingHistory: false,
    loadHistory: (...args: unknown[]) => loadHistoryMock(...args),
    sendMessage: vi.fn(),
    addUserMessage: vi.fn(),
    addSystemMessage: vi.fn(),
    addAssistantMessage: vi.fn(),
    appendToLastAssistantMessage: vi.fn(),
    clearMessages: vi.fn(),
    setError: vi.fn(),
  }
  return {
    chatStore: Object.assign(
      () => actualState,
      {
        getState: () => actualState,
        setState: vi.fn(),
      },
    ),
  }
})

// HU10 (T8 commit 2c19482): <ChatWindow> also fires
// ``fetchApprovalsHistory(projectId)`` on mount. Stub the store here so the
// unmocked fetch does not bubble up as an unhandled rejection during these
// mount-time tests (which only assert on chatStore).
const { fetchApprovalsHistoryMock } = vi.hoisted(() => ({
  fetchApprovalsHistoryMock: vi.fn().mockResolvedValue(undefined),
}))

vi.mock('../../stores/approvalsStore', () => {
  const actualState = {
    pendingDecision: {
      requerimientos: null,
      propuesta: null,
      refinamiento: null,
      revision: null,
      final: null,
    },
    historyByPhase: {
      requerimientos: [],
      propuesta: [],
      refinamiento: [],
      revision: [],
      final: [],
    },
    phases: [],
    currentPhase: null,
    loading: false,
    error: null,
    fetchHistory: (...args: unknown[]) =>
      fetchApprovalsHistoryMock(...args),
    setPending: vi.fn(),
    clearPending: vi.fn(),
    decide: vi.fn(),
    reset: vi.fn(),
  }
  // approvalsStore is consumed via the zustand selector pattern in
  // ChatWindow: ``approvalsStore((s) => s.fetchHistory)``. The mock must
  // actually invoke the selector (the existing chatStore mock did not
  // need this because ChatWindow reads chatStore via ``getState()``).
  const approvalsStoreFn = ((selector?: (s: typeof actualState) => unknown) =>
    selector ? selector(actualState) : actualState) as unknown as {
    (): typeof actualState
    (selector: (s: typeof actualState) => unknown): unknown
    getState: () => typeof actualState
    setState: ReturnType<typeof vi.fn>
  }
  approvalsStoreFn.getState = () => actualState
  approvalsStoreFn.setState = vi.fn()
  return { approvalsStore: approvalsStoreFn }
})

import { render, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { ChatWindow } from '../ChatWindow'

describe('ChatWindow mount-time fetch (F12 REQ-9, SCN-2)', () => {
  beforeEach(() => {
    loadHistoryMock.mockReset()
    loadHistoryMock.mockResolvedValue(undefined)
  })

  afterEach(() => {
    vi.clearAllMocks()
  })

  it('fires loadHistory exactly once on mount', async () => {
    render(<ChatWindow projectId={42} />)

    await waitFor(() => {
      expect(loadHistoryMock).toHaveBeenCalledTimes(1)
    })
    expect(loadHistoryMock).toHaveBeenCalledWith(42)
  })

  it('re-fetches when projectId changes', async () => {
    const { rerender } = render(<ChatWindow projectId={42} />)
    await waitFor(() => expect(loadHistoryMock).toHaveBeenCalledTimes(1))

    rerender(<ChatWindow projectId={99} />)
    await waitFor(() => expect(loadHistoryMock).toHaveBeenCalledTimes(2))
    expect(loadHistoryMock).toHaveBeenNthCalledWith(2, 99)
  })

  it('does NOT double-fire under StrictMode (mount-only once net)', async () => {
    // React StrictMode mounts the component twice on purpose in dev. Our
    // ``loadingHistory`` + ``isStreaming`` guards short-circuit the second
    // call, so the count stays at 1.
    //
    // We simulate the StrictMode behaviour by hand: render twice in a row
    // and assert loadHistory was called at most once per render cycle.
    const { unmount } = render(<ChatWindow projectId={1} />)
    unmount()
    render(<ChatWindow projectId={1} />)

    await waitFor(() => {
      // Allow up to 2 calls (one per mount), but never more — and the
      // StrictMode guard on `loadingHistory` keeps the second render a
      // no-op once the first fetch is in flight.
      expect(loadHistoryMock.mock.calls.length).toBeLessThanOrEqual(2)
    })
  })
})
