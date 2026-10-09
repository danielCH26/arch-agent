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

  describe('evento error estructurado', () => {
    async function runWith(errorFrame: string) {
      vi.stubGlobal(
        'fetch',
        vi.fn().mockResolvedValue({ ok: true, body: sseBody([errorFrame]) }),
      )
      const cb = callbacks()
      createProposalStream('generate', { project_id: 1 }, cb)
      await vi.waitFor(() => expect(cb.onError).toHaveBeenCalled())
      return cb
    }

    it('entrega mensaje y metadatos {code, retryable} sin tocar el texto', async () => {
      const payload = { message: 'Superó el tiempo máximo', code: 'timeout', retryable: true }

      const cb = await runWith(`event: error\ndata: ${JSON.stringify(payload)}\n\n`)

      expect(cb.onError).toHaveBeenCalledTimes(1)
      expect(cb.onError).toHaveBeenCalledWith('Superó el tiempo máximo', {
        code: 'timeout',
        retryable: true,
      })
    })

    it('un error permanente llega con retryable=false', async () => {
      const payload = { message: 'Máximo de iteraciones', code: 'rejected', retryable: false }

      const cb = await runWith(`event: error\ndata: ${JSON.stringify(payload)}\n\n`)

      expect(cb.onError).toHaveBeenCalledWith('Máximo de iteraciones', {
        code: 'rejected',
        retryable: false,
      })
    })

    it('retryable solo cuenta si es exactamente true (un "true" en texto no habilita el reintento)', async () => {
      const payload = { message: 'x', code: 'timeout', retryable: 'true' }

      const cb = await runWith(`event: error\ndata: ${JSON.stringify(payload)}\n\n`)

      expect(cb.onError).toHaveBeenCalledWith('x', { code: 'timeout', retryable: false })
    })

    it('un objeto sin code se acepta como no reintentable', async () => {
      const cb = await runWith('event: error\ndata: {"message":"algo falló"}\n\n')

      expect(cb.onError).toHaveBeenCalledWith('algo falló', { code: 'unknown', retryable: false })
    })

    it('un objeto sin message usa un texto genérico en vez de "undefined"', async () => {
      const cb = await runWith('event: error\ndata: {"code":"timeout","retryable":true}\n\n')

      expect(cb.onError).toHaveBeenCalledWith('Unknown error', { code: 'timeout', retryable: true })
    })

    it('un payload string (backend viejo) se muestra pero NUNCA habilita el reintento', async () => {
      const cb = await runWith(
        'event: error\ndata: "La generación superó el tiempo máximo (5 min)"\n\n',
      )

      expect(cb.onError).toHaveBeenCalledTimes(1)
      expect(cb.onError).toHaveBeenCalledWith('La generación superó el tiempo máximo (5 min)')
    })

    it('un payload que no es JSON se muestra como texto plano, sin metadatos', async () => {
      const cb = await runWith('event: error\ndata: fallo sin comillas\n\n')

      expect(cb.onError).toHaveBeenCalledWith('fallo sin comillas')
    })

    it('corta el stream tras el error (no procesa eventos posteriores)', async () => {
      vi.stubGlobal(
        'fetch',
        vi.fn().mockResolvedValue({
          ok: true,
          body: sseBody([
            'event: error\ndata: {"message":"m","code":"timeout","retryable":true}\n\n',
            'event: done\ndata: {"proposal_id": 1, "citations": []}\n\n',
          ]),
        }),
      )
      const cb = callbacks()

      createProposalStream('generate', { project_id: 1 }, cb)
      await vi.waitFor(() => expect(cb.onError).toHaveBeenCalled())

      expect(cb.onDone).not.toHaveBeenCalled()
    })
  })
})
