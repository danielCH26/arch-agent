import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { apiUrl, errorMessageFromResponse, safeFetch } from '../api/client'

// Datos por usuario guardados en el navegador (p. ej. la última propuesta de
// cada proyecto, ver proposalsStore): se borran al cerrar sesión.
const USER_SCOPED_STORAGE_PREFIX = 'archagent:user:'

function clearUserScopedStorage() {
  try {
    Object.keys(localStorage)
      .filter((key) => key.startsWith(USER_SCOPED_STORAGE_PREFIX))
      .forEach((key) => localStorage.removeItem(key))
  } catch {
    // Sin acceso a localStorage: no hay nada que limpiar.
  }
}

interface User {
  id: number
  username: string
  email?: string
}

interface AuthState {
  token: string | null
  user: User | null
  status: 'idle' | 'loading' | 'error'
  error: string | null

  login: (username: string, password: string) => Promise<void>
  register: (username: string, email: string, password: string) => Promise<void>
  logout: () => Promise<void>
  loadUser: () => Promise<void>
  clearError: () => void
  updateUser: (updates: Partial<User>) => void
}

export const authStore = create<AuthState>()(
  persist(
    (set, get) => ({
      token: null,
      user: null,
      status: 'idle',
      error: null,

      login: async (username: string, password: string) => {
        set({ status: 'loading', error: null })
        try {
          const response = await safeFetch(apiUrl('/api/auth/login'), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password }),
          })

          if (!response.ok) {
            const data = await response.json().catch(() => ({}))
            throw new Error(
              response.status === 401
                ? (typeof data.detail === 'string' && data.detail) || 'Usuario o contraseña incorrectos.'
                : errorMessageFromResponse(response.status, data),
            )
          }

          const data = await response.json() as { user_id: number; username: string; token: string }
          set({
            token: data.token,
            user: { id: data.user_id, username: data.username },
            status: 'idle',
          })
        } catch (error) {
          const message = error instanceof Error ? error.message : 'No se pudo iniciar sesión.'
          set({ status: 'error', error: message })
          throw error
        }
      },

      register: async (username: string, email: string, password: string) => {
        set({ status: 'loading', error: null })
        try {
          const response = await safeFetch(apiUrl('/api/auth/register'), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, email, password }),
          })

          if (!response.ok) {
            const data = await response.json().catch(() => ({}))
            throw new Error(errorMessageFromResponse(response.status, data))
          }

          const data = await response.json() as { user_id: number; username: string; token: string }
          set({
            token: data.token,
            user: { id: data.user_id, username: data.username },
            status: 'idle',
          })
        } catch (error) {
          const message = error instanceof Error ? error.message : 'No se pudo crear la cuenta.'
          set({ status: 'error', error: message })
          throw error
        }
      },

      logout: async () => {
        const token = get().token
        if (token) {
          try {
            await fetch(apiUrl('/api/auth/logout'), {
              method: 'POST',
              headers: { Authorization: `Bearer ${token}` },
            })
          } catch {
            // Ignore logout errors
          }
        }
        clearUserScopedStorage()
        set({ token: null, user: null, status: 'idle', error: null })
      },

      loadUser: async () => {
        const token = get().token
        if (!token) return

        set({ status: 'loading' })
        try {
          const response = await fetch(apiUrl('/api/auth/me'), {
            headers: { Authorization: `Bearer ${token}` },
          })

          if (!response.ok) {
            // Token invalid or expired
            set({ token: null, user: null, status: 'idle' })
            return
          }

          const user = await response.json() as { id: number; username: string; email: string }
          set({ user: { id: user.id, username: user.username, email: user.email }, status: 'idle' })
        } catch {
          set({ token: null, user: null, status: 'idle' })
        }
      },

      clearError: () => set({ error: null }),

      updateUser: (updates: Partial<User>) => {
        const currentUser = get().user
        if (currentUser) {
          set({ user: { ...currentUser, ...updates } })
        }
      },
    }),
    {
      name: 'auth-storage',
      partialize: (state) => ({ token: state.token, user: state.user }),
    }
  )
)
