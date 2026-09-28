import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { apiFetch } from '../client'
import { authStore } from '../../stores/authStore'

const { mockRedirectToLogin } = vi.hoisted(() => ({
  mockRedirectToLogin: vi.fn(),
}))

// Mock the authStore
vi.mock('../../stores/authStore', () => ({
  authStore: {
    getState: vi.fn(),
  },
}))

vi.mock('../navigation', () => ({
  redirectToLogin: mockRedirectToLogin,
}))

describe('apiFetch', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('adds Authorization header when token exists', async () => {
    const mockToken = 'test-token-123'
    ;(authStore.getState as vi.Mock).mockReturnValue({ token: mockToken })

    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ result: 'ok' }),
    })
    global.fetch = mockFetch

    await apiFetch('/api/test', { method: 'GET' })

    expect(mockFetch).toHaveBeenCalledWith(
      '/api/test',
      expect.objectContaining({
        method: 'GET',
        headers: expect.objectContaining({
          Authorization: `Bearer ${mockToken}`,
        }),
      })
    )
  })

  it('does not add Authorization header when no token', async () => {
    ;(authStore.getState as vi.Mock).mockReturnValue({ token: null })

    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ result: 'ok' }),
    })
    global.fetch = mockFetch

    await apiFetch('/api/test', { method: 'GET' })

    expect(mockFetch).toHaveBeenCalledWith(
      '/api/test',
      expect.objectContaining({
        method: 'GET',
        headers: expect.not.objectContaining({
          Authorization: expect.any(String),
        }),
      })
    )
  })

  it('redirects to /login on 401', async () => {
    ;(authStore.getState as vi.Mock).mockReturnValue({ token: 'expired-token' })

    const mockLogout = vi.fn()
    ;(authStore.getState as vi.Mock).mockReturnValue({
      token: 'expired-token',
      logout: mockLogout,
    })

    const mockFetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      json: () => Promise.resolve({ detail: 'Unauthorized' }),
    })
    global.fetch = mockFetch

    await expect(apiFetch('/api/test')).rejects.toThrow()

    expect(mockLogout).toHaveBeenCalled()
    expect(mockRedirectToLogin).toHaveBeenCalledOnce()
  })

  it('throws ApiError with status on non-ok response', async () => {
    ;(authStore.getState as vi.Mock).mockReturnValue({ token: null })

    const mockFetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 400,
      json: () => Promise.resolve({ detail: 'Bad request' }),
    })
    global.fetch = mockFetch

    await expect(apiFetch('/api/test')).rejects.toThrow()
  })
})
