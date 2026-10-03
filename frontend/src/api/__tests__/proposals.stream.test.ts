import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createProposalStream, type ProposalProgress } from '../proposals'

vi.mock('../../stores/authStore', () => ({
  authStore: { getState: () => ({ token: 'tok' }) },
}))

function sseBody(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder()
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk))
      controller.close()
    },
  })
}

function callbacks() {
  return {
    onToken: vi.fn(),
    onSources: vi.fn(),
    onProgress: vi.fn(),
    onDone: vi.fn(),
    onError: vi.fn(),
  }
}

describe('createProposalStream (F19)', () => {
  beforeEach(() => vi.restoreAllMocks())
  afterEach(() => vi.unstubAllGlobals())

  it('despacha los eventos progress al callback y sigue con tokens y done', async () => {
    const progress: ProposalProgress = {
      stage: 'retrieval',
      percent: 12,
      message: 'Buscando patrones de arquitectura relevantes',
      elapsed_ms: 800,
      budget_s: 300,
    }
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        body: sseBody([
          `event: progress\ndata: ${JSON.stringify(progress)}\n\n`,
          'event: token\ndata: "Hola"\n\n',
          'event: done\ndata: {"proposal_id": 9, "citations": [], "iteration": 1, "elapsed_ms": 4000}\n\n',
        ]),
      }),
    )
    const cb = callbacks()

    createProposalStream('generate', { project_id: 1 }, cb)
    await vi.waitFor(() => expect(cb.onDone).toHaveBeenCalled())

    expect(cb.onProgress).toHaveBeenCalledWith(progress)
    expect(cb.onToken).toHaveBeenCalledWith('Hola')
    expect(cb.onDone).toHaveBeenCalledWith(9, [], 1)
    expect(cb.onError).not.toHaveBeenCalled()
  })

  it('ignora un progress ilegible y no rompe la generación', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        body: sseBody([
          'event: progress\ndata: {no-json\n\n',
          'event: done\ndata: {"proposal_id": 1, "citations": []}\n\n',
        ]),
      }),
    )
    const cb = callbacks()

    createProposalStream('generate', { project_id: 1 }, cb)
    await vi.waitFor(() => expect(cb.onDone).toHaveBeenCalled())

    expect(cb.onProgress).not.toHaveBeenCalled()
    expect(cb.onError).not.toHaveBeenCalled()
  })

  it('funciona sin onProgress (consumidores que no muestran progreso)', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        body: sseBody([
          'event: progress\ndata: {"stage":"context","percent":3}\n\n',
          'event: done\ndata: {"proposal_id": 2, "citations": []}\n\n',
        ]),
      }),
    )
    const { onProgress: _omit, ...cb } = callbacks()

    createProposalStream('generate', { project_id: 1 }, cb)
    await vi.waitFor(() => expect(cb.onDone).toHaveBeenCalled())
    expect(cb.onError).not.toHaveBeenCalled()
  })

  it('la función devuelta aborta el fetch y el abort NO se reporta como error', async () => {
    let seenSignal: AbortSignal | undefined
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation((_url: string, init: RequestInit) => {
        seenSignal = init.signal as AbortSignal
        return new Promise((_resolve, reject) => {
          seenSignal!.addEventListener('abort', () =>
            reject(new DOMException('Aborted', 'AbortError')),
          )
        })
      }),
    )
    const cb = callbacks()

    const abort = createProposalStream('generate', { project_id: 1 }, cb)
    abort()
    await Promise.resolve()
    await Promise.resolve()

    expect(seenSignal?.aborted).toBe(true)
    expect(cb.onError).not.toHaveBeenCalled()
    expect(cb.onDone).not.toHaveBeenCalled()
  })
})
