import { authStore } from '../stores/authStore'
import { redirectToLogin } from './navigation'

const BASE_URL = import.meta.env.VITE_API_BASE_URL || ''

// El backend responde `detail` como string (errores legacy) o como objeto
// tipado `{ error: '<codigo>', ... }` (REQ-SA-28 / REQ-SA-34). Castear un
// objeto a string mostraba "[object Object]" en la UI.
const DETAIL_ERROR_MESSAGES: Record<string, string> = {
  phase_mismatch:
    'La fase del proyecto cambió. Recarga la pantalla e inténtalo de nuevo.',
  phase_not_approved: 'La fase actual todavía no está aprobada.',
  validation_error: 'La acción no es válida para esta fase.',
  internal_error: 'Ocurrió un error inesperado. Inténtalo de nuevo.',
}

export function detailToMessage(detail: unknown): string | null {
  if (typeof detail === 'string' && detail) return detail
  if (detail && typeof detail === 'object') {
    const d = detail as { error?: unknown; message?: unknown }
    if (typeof d.message === 'string' && d.message) return d.message
    if (typeof d.error === 'string') return DETAIL_ERROR_MESSAGES[d.error] ?? null
  }
  return null
}

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
    redirectToLogin()
    throw new ApiError(401, 'Session expired')
  }

  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new ApiError(res.status, detailToMessage(data.detail) || 'Request failed', data)
  }

  // 204 No Content no tiene body para parsear
  if (res.status === 204) {
    return undefined as T
  }

  return res.json() as Promise<T>
}
