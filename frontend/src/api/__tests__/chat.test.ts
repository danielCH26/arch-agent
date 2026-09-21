import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  _normaliseHistoryAttachments,
  fetchChatHistory,
} from '../chat'
import { authStore } from '../../stores/authStore'

// Mock the authStore so fetchChatHistory sees a known Bearer token (or none).
vi.mock('../../stores/authStore', () => ({
  authStore: {
    getState: vi.fn(),
  },
}))

describe('_normaliseHistoryAttachments (PR #76 review fix #6a)', () => {
  it('returns [] when input is not an array', () => {
    expect(_normaliseHistoryAttachments(undefined)).toEqual([])
    expect(_normaliseHistoryAttachments(null)).toEqual([])
    expect(_normaliseHistoryAttachments('not-an-array')).toEqual([])
    expect(_normaliseHistoryAttachments({ kind: 'screenshot' })).toEqual([])
    expect(_normaliseHistoryAttachments(42)).toEqual([])
  })

  it('keeps well-formed screenshot attachments', () => {
    const att = {
      kind: 'screenshot' as const,
      mime: 'image/png' as const,
      url: '/api/chat/attachments/abc?token=xyz',
      filename: 'diagram.png',
    }
    expect(_normaliseHistoryAttachments([att])).toEqual([att])
  })

  it('drops items that are not objects', () => {
    const att = {
      kind: 'screenshot' as const,
      mime: 'image/png' as const,
      url: '/api/chat/attachments/x?token=y',
      filename: 'd.png',
    }
    expect(_normaliseHistoryAttachments([att, null, 'str', 42, undefined])).toEqual([att])
  })

  it('drops items whose kind is not "screenshot"', () => {
    const good = {
      kind: 'screenshot' as const,
      mime: 'image/png' as const,
      url: '/api/chat/attachments/x?token=y',
      filename: 'd.png',
    }
    expect(
      _normaliseHistoryAttachments([
        good,
        { kind: 'video', mime: 'video/mp4', url: 'u', filename: 'v.mp4' },
        { kind: 'document', mime: 'application/pdf', url: 'u', filename: 'doc.pdf' },
      ]),
    ).toEqual([good])
  })

  it('drops items missing a string url', () => {
    const good = {
      kind: 'screenshot' as const,
      mime: 'image/png' as const,
      url: '/api/chat/attachments/x?token=y',
      filename: 'd.png',
    }
    expect(
      _normaliseHistoryAttachments([
        good,
        { kind: 'screenshot', mime: 'image/png', url: undefined, filename: 'no-url' },
        { kind: 'screenshot', mime: 'image/png', url: 42, filename: 'bad-url' },
      ]),
    ).toEqual([good])
  })
})

describe('fetchChatHistory (PR #76 review fix #6a)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    ;(authStore.getState as vi.Mock).mockReturnValue({ token: 'jwt' })
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('normalises attachments via _normaliseHistoryAttachments on every row', async () => {
    const good = {
      kind: 'screenshot',
      mime: 'image/png',
      url: '/api/chat/attachments/x?token=y',
      filename: 'd.png',
    }

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () =>
        Promise.resolve({
          messages: [
            // F13 row with one good attachment + one malformed entry
            {
              id: 1,
              role: 'assistant',
              content: 'a1',
              citations: [],
              attachments: [
                good,
                { kind: 'document', mime: 'application/pdf', url: 'x', filename: 'doc.pdf' },
                null,
                'raw-string',
              ],
              created_at: '2024-01-01T12:00:01Z',
            },
            // Pre-F13 row whose column is missing entirely
            {
              id: 2,
              role: 'user',
              content: 'u2',
              citations: [],
              created_at: '2024-01-01T12:00:02Z',
            },
            // F13 row with ``null`` attachments (corrupted payload)
            {
              id: 3,
              role: 'assistant',
              content: 'a3',
              citations: [],
              attachments: null,
              created_at: '2024-01-01T12:00:03Z',
            },
          ],
        }),
    })
    global.fetch = fetchMock

    const out = await fetchChatHistory(42, 5)

    expect(out).toHaveLength(3)
    expect(out[0].attachments).toEqual([good])
    expect(out[1].attachments).toEqual([])
    expect(out[2].attachments).toEqual([])
  })

  it('returns an empty array when the payload has no messages field', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve({}),
    })
    global.fetch = fetchMock

    const out = await fetchChatHistory(7, 5)
    expect(out).toEqual([])
  })

  it('clamps limit into [1, 50] (REQ-7 contract)', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ messages: [] }),
    })
    global.fetch = fetchMock

    await fetchChatHistory(7, -10)
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('limit=1'),
      expect.any(Object),
    )

    fetchMock.mockClear()

    await fetchChatHistory(7, 9999)
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('limit=50'),
      expect.any(Object),
    )
  })
})
