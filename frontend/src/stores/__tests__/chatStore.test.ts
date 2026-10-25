import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

// Mock the API module BEFORE importing the store.
vi.mock('../../api/chat', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/chat')>()
  return {
    ...actual,
    fetchChatHistory: vi.fn(),
    createChatStream: vi.fn(),
  }
})

import { createChatStream, fetchChatHistory } from '../../api/chat'
import { chatStore, HISTORY_LIMIT } from '../chatStore'

const fetchChatHistoryMock = vi.mocked(fetchChatHistory)
const createChatStreamMock = vi.mocked(createChatStream)

type Callbacks = Parameters<typeof createChatStream>[2]

// Callbacks de cada stream iniciado, para manejarlos desde el test.
let streams: Callbacks[] = []

function resetStore() {
  chatStore.setState({
    messages: [],
    isStreaming: false,
    error: null,
    loadingHistory: false,
    activeProjectId: null,
    historyTruncated: false,
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  streams = []
  createChatStreamMock.mockImplementation((_message, _projectId, callbacks) => {
    streams.push(callbacks)
    return () => undefined
  })
  fetchChatHistoryMock.mockResolvedValue([])
  resetStore()
  // Drop the persisted auth token so fetchChatHistory does not pass a Bearer header.
  localStorage.clear()
})

afterEach(() => {
  // Cerrar los streams abiertos para no dejar proyectos "en curso"
  // (el store recuerda en un módulo qué proyectos tienen respuesta en curso).
  streams.forEach((callbacks) => callbacks.onDone())
})

describe('chatStore.loadHistory', () => {
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
      messages: [{ id: 'optimistic-1', role: 'user', content: 'pending' }],
    })

    fetchChatHistoryMock.mockResolvedValue([
      { id: 9, role: 'assistant', content: 'server reply', citations: [], created_at: '2024-01-01T12:00:09Z' },
    ])

    await chatStore.getState().loadHistory(42)

    expect(chatStore.getState().messages).toHaveLength(1)
    expect(chatStore.getState().messages[0].content).toBe('server reply')
  })

  it('on error, clears loadingHistory, reports the error and never shows another project (REQ-8)', async () => {
    // Mensajes de otro proyecto: no deben quedar visibles en el proyecto 42.
    chatStore.setState({
      activeProjectId: 7,
      messages: [{ id: 'seed-1', role: 'user', content: 'mensaje del proyecto 7' }],
    })

    fetchChatHistoryMock.mockRejectedValue(new Error('network down'))

    await chatStore.getState().loadHistory(42)

    const state = chatStore.getState()
    expect(state.loadingHistory).toBe(false)
    expect(state.error).toBe('network down')
    expect(state.messages).toEqual([])
  })

  it('passes projectId + limit to fetchChatHistory (REQ-7)', async () => {
    await chatStore.getState().loadHistory(123, 10)

    expect(fetchChatHistoryMock).toHaveBeenCalledWith(123, 10)
  })

  it(`defaults limit to HISTORY_LIMIT (${HISTORY_LIMIT}) when not provided`, async () => {
    await chatStore.getState().loadHistory(7)

    expect(fetchChatHistoryMock).toHaveBeenCalledWith(7, HISTORY_LIMIT)
  })

  it('marca el historial como truncado al llegar al límite de la API', async () => {
    fetchChatHistoryMock.mockResolvedValue(
      Array.from({ length: HISTORY_LIMIT }, (_, id) => ({ id, role: 'user' as const, content: `m${id}`, created_at: null })),
    )
    await chatStore.getState().loadHistory(3)
    expect(chatStore.getState().historyTruncated).toBe(true)
  })

  // ----- F13 (REQ-ATT-3): loadHistory propagates attachments ------------

  it('propagates attachments from the history payload', async () => {
    fetchChatHistoryMock.mockResolvedValue([
      {
        id: 5,
        role: 'assistant',
        content: 'a5',
        citations: [],
        attachments: [
          {
            kind: 'screenshot',
            mime: 'image/png',
            url: '/api/chat/attachments/abc?token=t',
            filename: 'diagram-5.png',
          },
        ],
        created_at: '2024-01-01T12:00:05Z',
      },
    ])

    await chatStore.getState().loadHistory(42)

    const state = chatStore.getState()
    expect(state.messages).toHaveLength(1)
    expect(state.messages[0].attachments).toEqual([
      {
        kind: 'screenshot',
        mime: 'image/png',
        url: '/api/chat/attachments/abc?token=t',
        filename: 'diagram-5.png',
      },
    ])
  })
})

describe('chatStore.sendMessage attachments', () => {
  it('appends an attachment received via onAttachment to the in-flight assistant message', async () => {
    await chatStore.getState().sendMessage(1, 'dame un diagrama')

    const assistant = chatStore.getState().messages.find((m) => m.role === 'assistant')
    expect(assistant).toBeDefined()
    expect(assistant!.attachments ?? []).toEqual([])

    // Simulate the SSE ``event: attachment`` arriving mid-stream.
    streams[0].onAttachment?.({
      kind: 'screenshot',
      mime: 'image/png',
      url: '/api/chat/attachments/uuid?token=jwt',
      filename: 'diagram-12345.png',
    })

    const assistantAfter = chatStore.getState().messages.find((m) => m.role === 'assistant')
    expect(assistantAfter!.attachments).toEqual([
      {
        kind: 'screenshot',
        mime: 'image/png',
        url: '/api/chat/attachments/uuid?token=jwt',
        filename: 'diagram-12345.png',
      },
    ])
  })

  it('preserves attachment order across multiple onAttachment calls', async () => {
    await chatStore.getState().sendMessage(1, 'dos diagramas')

    const a1 = {
      kind: 'screenshot' as const,
      mime: 'image/png' as const,
      url: '/api/chat/attachments/a1?token=t',
      filename: 'a1.png',
    }
    const a2 = {
      kind: 'screenshot' as const,
      mime: 'image/png' as const,
      url: '/api/chat/attachments/a2?token=t',
      filename: 'a2.png',
    }
    streams[0].onAttachment?.(a1)
    streams[0].onAttachment?.(a2)

    const assistant = chatStore.getState().messages.find((m) => m.role === 'assistant')
    expect(assistant!.attachments).toEqual([a1, a2])
  })
})

describe('chatStore.sendMessage concurrencia y proyectos', () => {
  it('no inicia un segundo stream mientras hay una respuesta en curso', async () => {
    expect(await chatStore.getState().sendMessage(1, 'Hola')).toBe(true)
    expect(await chatStore.getState().sendMessage(1, 'Otra')).toBe(false)
    expect(createChatStreamMock).toHaveBeenCalledTimes(1)

    streams[0].onDone()
    expect(await chatStore.getState().sendMessage(1, 'Otra')).toBe(true)
  })

  it('al volver a un proyecto con respuesta en curso, bloquea el input y recarga al terminar', async () => {
    await chatStore.getState().sendMessage(1, 'Pregunta del proyecto 1')

    await chatStore.getState().loadHistory(2)
    expect(chatStore.getState().isStreaming).toBe(false)

    await chatStore.getState().loadHistory(1)
    expect(chatStore.getState().isStreaming).toBe(true)

    fetchChatHistoryMock.mockClear()
    streams[0].onDone()
    expect(chatStore.getState().isStreaming).toBe(false)
    expect(fetchChatHistoryMock).toHaveBeenCalledWith(1, HISTORY_LIMIT)
  })

  it('un corte del stream conserva la respuesta parcial y muestra el error', async () => {
    await chatStore.getState().sendMessage(1, 'Hola')
    streams[0].onToken('Respuesta parcial')
    streams[0].onError('La respuesta se interrumpió antes de terminar. Inténtalo de nuevo.')

    const state = chatStore.getState()
    expect(state.isStreaming).toBe(false)
    expect(state.error).toMatch(/interrumpió/)
    expect(state.messages.at(-1)?.content).toBe('Respuesta parcial')
  })
})
