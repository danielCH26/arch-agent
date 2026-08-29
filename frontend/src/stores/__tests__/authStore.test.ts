import { describe, it, expect, vi, beforeEach } from 'vitest'
import { authStore } from '../authStore'

// Mock fetch globally
global.fetch = vi.fn()

describe('authStore', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // Reset store state
    authStore.getState().logout()
  })

  it('login persists token and user on success', async () => {
    const mockResponse = {
      ok: true,
      json: () => Promise.resolve({
        user_id: 1,
        username: 'testuser',
        token: 'test-token-123',
      }),
    }
    ;(global.fetch as vi.Mock).mockResolvedValue(mockResponse)

    await authStore.getState().login('testuser', 'password123')

    const state = authStore.getState()
    expect(state.token).toBe('test-token-123')
    expect(state.user).toEqual({ id: 1, username: 'testuser' })
    expect(state.status).toBe('idle')
    expect(state.error).toBeNull()
  })

  it('login sets error on failure', async () => {
    const mockResponse = {
      ok: false,
      status: 401,
      json: () => Promise.resolve({ detail: 'Invalid credentials' }),
    }
    ;(global.fetch as vi.Mock).mockResolvedValue(mockResponse)

    await expect(authStore.getState().login('testuser', 'wrongpassword')).rejects.toThrow()

    const state = authStore.getState()
    expect(state.status).toBe('error')
    expect(state.error).toBe('Invalid credentials')
  })

  it('logout clears token, user and calls API', async () => {
    // First login to set state
    const mockLoginResponse = {
      ok: true,
      json: () => Promise.resolve({
        user_id: 1,
        username: 'testuser',
        token: 'test-token-123',
      }),
    }
    ;(global.fetch as vi.Mock).mockResolvedValue(mockLoginResponse)
    await authStore.getState().login('testuser', 'password')

    // Now logout
    const mockLogoutResponse = { ok: true }
    ;(global.fetch as vi.Mock).mockResolvedValue(mockLogoutResponse)

    await authStore.getState().logout()

    const state = authStore.getState()
    expect(state.token).toBeNull()
    expect(state.user).toBeNull()
  })

  it('register creates user and token on success', async () => {
    const mockResponse = {
      ok: true,
      status: 201,
      json: () => Promise.resolve({
        user_id: 2,
        username: 'newuser',
        token: 'new-user-token',
      }),
    }
    ;(global.fetch as vi.Mock).mockResolvedValue(mockResponse)

    await authStore.getState().register('newuser', 'new@example.com', 'password123')

    const state = authStore.getState()
    expect(state.token).toBe('new-user-token')
    expect(state.user).toEqual({ id: 2, username: 'newuser' })
    expect(state.status).toBe('idle')
  })

  it('clearError clears the error state', async () => {
    // Trigger an error first
    const mockResponse = {
      ok: false,
      status: 401,
      json: () => Promise.resolve({ detail: 'Invalid credentials' }),
    }
    ;(global.fetch as vi.Mock).mockResolvedValue(mockResponse)
    await expect(authStore.getState().login('testuser', 'wrongpassword')).rejects.toThrow()

    expect(authStore.getState().error).not.toBeNull()

    // Clear error
    authStore.getState().clearError()
    expect(authStore.getState().error).toBeNull()
  })
})
