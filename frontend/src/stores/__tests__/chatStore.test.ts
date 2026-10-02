import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { chatStore, HISTORY_LIMIT } from '../chatStore'
import { createChatStream, fetchChatHistory } from '../../api/chat'

vi.mock('../../api/chat', () => ({
  createChatStream: vi.fn(),
  fetchChatHistory: vi.fn(),
}))

type Callbacks = Parameters<typeof createChatStream>[2]

// Guarda los callbacks de cada stream para terminarlos desde el test.
let streams: Callbacks[] = []

describe('chatStore', () => {
  beforeEach(() => {
    streams = []
    vi.mocked(createChatStream).mockImplementation((_message, _projectId, callbacks) => {
      streams.push(callbacks)
      return () => {}
    })
    vi.mocked(fetchChatHistory).mockResolvedValue([])
    chatStore.setState({ messages: [], isStreaming: false, error: null, loadingHistory: false, activeProjectId: null })
  })

  afterEach(() => {
    // Cerrar los streams abiertos para no dejar proyectos "en curso".
    streams.forEach((callbacks) => callbacks.onDone())
  })

  it('no inicia un segundo stream mientras hay una respuesta en curso', async () => {
    expect(await chatStore.getState().sendMessage(1, 'Hola')).toBe(true)
    expect(await chatStore.getState().sendMessage(1, 'Otra')).toBe(false)
    expect(createChatStream).toHaveBeenCalledTimes(1)

    streams[0].onDone()
    expect(await chatStore.getState().sendMessage(1, 'Otra')).toBe(true)
  })

  it('al volver a un proyecto con respuesta en curso, bloquea el input y recarga al terminar', async () => {
    await chatStore.getState().sendMessage(1, 'Pregunta del proyecto 1')

    await chatStore.getState().loadHistory(2)
    expect(chatStore.getState().isStreaming).toBe(false)

    await chatStore.getState().loadHistory(1)
    expect(chatStore.getState().isStreaming).toBe(true)

    vi.mocked(fetchChatHistory).mockClear()
    streams[0].onDone()
    expect(chatStore.getState().isStreaming).toBe(false)
    expect(fetchChatHistory).toHaveBeenCalledWith(1, HISTORY_LIMIT)
  })

  it('marca el historial como truncado al llegar al límite de la API', async () => {
    vi.mocked(fetchChatHistory).mockResolvedValue(
      Array.from({ length: HISTORY_LIMIT }, (_, id) => ({ id, role: 'user' as const, content: `m${id}`, created_at: null })),
    )
    await chatStore.getState().loadHistory(3)
    expect(chatStore.getState().historyTruncated).toBe(true)
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
