import { create } from 'zustand'
import { createJSONStorage, persist, type StateStorage } from 'zustand/middleware'
import { apiUrl, errorMessageFromResponse, safeFetch } from '../api/client'

// Datos por usuario guardados en el navegador (p. ej. la última propuesta de
// cada proyecto, ver proposalsStore): se borran al cerrar sesión.
const USER_SCOPED_STORAGE_PREFIX = 'archagent:user:'

function clearUserScopedStorage(userId?: number) {
  // Solo las del usuario que cierra sesión: otra pestaña puede seguir con
  // otra cuenta (ver tabSessionStorage).
  const prefix = userId === undefined ? USER_SCOPED_STORAGE_PREFIX : `${USER_SCOPED_STORAGE_PREFIX}${userId}:`
  try {
    Object.keys(localStorage)
      .filter((key) => key.startsWith(prefix))
      .forEach((key) => localStorage.removeItem(key))
  } catch {
    // Sin acceso a localStorage: no hay nada que limpiar.
  }
}

// Sesión POR PESTAÑA. Antes la sesión vivía solo en localStorage, que
// comparten todas las pestañas: con una pestaña abierta como el usuario A,
// iniciar sesión como B en otra pestaña cambiaba también la cuenta de la
// primera, y su proyecto aparecía como "no disponible para tu usuario".
//
// Ahora cada pestaña guarda su sesión en sessionStorage (no se comparte) y
// localStorage solo recuerda la ÚLTIMA sesión iniciada, para que una pestaña
// nueva no tenga que volver a iniciar sesión.
export const tabSessionStorage: StateStorage = {
  getItem: (name) => {
    try {
      return sessionStorage.getItem(name) ?? localStorage.getItem(name)
    } catch {
      return null
    }
  },
  setItem: (name, value) => {
    try {
      sessionStorage.setItem(name, value)
      localStorage.setItem(name, value)
    } catch {
      // Sin almacenamiento (modo privado estricto): la sesión vive en memoria.
    }
  },
  removeItem: (name) => {
    try {
      const own = sessionStorage.getItem(name)
      sessionStorage.removeItem(name)
      // La "última sesión" solo se borra si es la de esta pestaña.
      if (own === null || localStorage.getItem(name) === own) localStorage.removeItem(name)
    } catch {
      // Sin almacenamiento: nada que borrar.
    }
  },
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
        clearUserScopedStorage(get().user?.id)
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
      storage: createJSONStorage(() => tabSessionStorage),
      partialize: (state) => ({ token: state.token, user: state.user }),
    }
  )
)

/** Aviso cuando el proyecto no es de la cuenta con la que está esta pestaña. */
export function projectUnavailableMessage(): string {
  const username = authStore.getState().user?.username
  return username
    ? `Ese proyecto no está disponible para la cuenta «${username}». Si es de otra cuenta, ábrelo en la pestaña donde iniciaste sesión con ella.`
    : 'Ese proyecto ya no está disponible para tu usuario.'
}
