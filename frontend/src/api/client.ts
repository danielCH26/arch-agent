import { authStore } from '../stores/authStore'

const BASE_URL = import.meta.env.VITE_API_BASE_URL || ''

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public data?: unknown
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

export async function apiFetch<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const token = authStore.getState().token
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string> || {}),
  }
  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }

  const res = await fetch(`${BASE_URL}${path}`, {
    ...options,
    headers,
  })

  if (res.status === 401) {
    // Token inválido o expirado — limpiar estado y redirigir
    authStore.getState().logout()
    // Redirigir usando replace para no agregar a historial
    window.location.replace('/login')
    throw new ApiError(401, 'Session expired')
  }

  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new ApiError(res.status, (data.detail as string) || 'Request failed', data)
  }

  // 204 No Content no tiene body para parsear
  if (res.status === 204) {
    return undefined as T
  }

  return res.json() as Promise<T>
}
