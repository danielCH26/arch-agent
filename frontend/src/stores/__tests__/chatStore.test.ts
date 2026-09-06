import { beforeEach, describe, expect, it, vi } from 'vitest'

// Mock the API module BEFORE importing the store.
vi.mock('../../api/chat', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/chat')>()
  return {
    ...actual,
    fetchChatHistory: vi.fn(),
  }
})

import { fetchChatHistory } from '../../api/chat'
import { chatStore } from '../chatStore'

const fetchChatHistoryMock = vi.mocked(fetchChatHistory)

describe('chatStore.loadHistory', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // Reset the store between tests so messages / loadingHistory are clean.
    chatStore.setState({
      messages: [],
      isStreaming: false,
      error: null,
      loadingHistory: false,
    })
    // Drop the persisted auth token so fetchChatHistory does not pass a Bearer header.
    localStorage.clear()
  })

  it('sets loadingHistory=true while in flight and false on success (REQ-8)', async () => {
    fetchChatHistoryMock.mockResolvedValue([
      { id: 3, role: 'assistant', content: 'a3', citations: [], created_at: '2024-01-01T12:00:03Z' },
      { id: 2, role: 'user', content: 'u2', citations: [], created_at: '2024-01-01T12:00:02Z' },
      { id: 1, role: 'assistant', content: 'a1', citations: [], created_at: '2024-01-01T12:00:01Z' },
    ])

    const promise = chatStore.getState().loadHistory(42)
    expect(chatStore.getState().loadingHistory).toBe(true)

    await promise

    const state = chatStore.getState()
    expect(state.loadingHistory).toBe(false)
    // Chronological (oldest-first) so the conversation reads top-to-bottom.
    expect(state.messages.map((m) => m.content)).toEqual(['a1', 'u2', 'a3'])
    // IDs are namespaced so they don't collide with optimistic local IDs.
    expect(state.messages.map((m) => m.id)).toEqual(['history-1', 'history-2', 'history-3'])
  })

  it('replaces messages atomically (not append) (REQ-8)', async () => {
    // Seed an in-flight optimistic message before loadHistory runs.
    chatStore.setState({
      messages: [
        { id: 'optimistic-1', role: 'user', content: 'pending' },
      ],
    })

    fetchChatHistoryMock.mockResolvedValue([
      { id: 9, role: 'assistant', content: 'server reply', citations: [], created_at: '2024-01-01T12:00:09Z' },
    ])

    await chatStore.getState().loadHistory(42)

    expect(chatStore.getState().messages).toHaveLength(1)
    expect(chatStore.getState().messages[0].content).toBe('server reply')
  })

  it('on error, leaves messages untouched and clears loadingHistory (REQ-8)', async () => {
    const initialMessages = [
      { id: 'seed-1', role: 'user' as const, content: 'do not lose me' },
    ]
    chatStore.setState({ messages: initialMessages })

    fetchChatHistoryMock.mockRejectedValue(new Error('network down'))

    await chatStore.getState().loadHistory(42)

    const state = chatStore.getState()
    expect(state.loadingHistory).toBe(false)
    expect(state.messages).toEqual(initialMessages)
  })

  it('passes projectId + limit to fetchChatHistory (REQ-7)', async () => {
    fetchChatHistoryMock.mockResolvedValue([])

    await chatStore.getState().loadHistory(123, 10)

    expect(fetchChatHistoryMock).toHaveBeenCalledWith(123, 10)
  })

  it('defaults limit to 5 when not provided (SCN-3)', async () => {
    fetchChatHistoryMock.mockResolvedValue([])

    await chatStore.getState().loadHistory(7)

    expect(fetchChatHistoryMock).toHaveBeenCalledWith(7, 5)
  })
})
