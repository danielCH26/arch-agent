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

/**
 * Extrae un mensaje de error legible desde el body de un response no-ok.
 *
 * Tolera los formatos de error que devuelve FastAPI (y los providers externos):
 * - { detail: "string" }    -> "string"
 * - { detail: [{...}, ...]} -> "[{msg1}, {msg2}]" (cada msg con su campo)
 * - { detail: {...} }       -> "<key>: <value>" del objeto
 * - { message: "string" }  -> "string"
 * - { error: "string" }     -> "string"
 * - cualquier otra cosa     -> ''
 *
 * Nunca devuelve un objeto sin stringificar — evita el bug [object Object]
 * que aparece cuando el frontend renderiza `err.message` y el backend
 * devolvio `detail` como array/objeto.
 */
export function extractDetail(data: unknown): string {
  if (!data || typeof data !== 'object') return ''
  const obj = data as Record<string, unknown>

  // FastAPI HTTPException detail
  const detail = obj.detail
  if (typeof detail === 'string' && detail) return detail
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        if (typeof item === 'string') return item
        if (item && typeof item === 'object') {
          // Validation errors: { loc: [...], msg: "...", type: "..."}
          const i = item as Record<string, unknown>
          const loc = Array.isArray(i.loc) ? i.loc.join('.') : ''
          const msg = typeof i.msg === 'string' ? i.msg : JSON.stringify(i)
          return loc ? `${loc}: ${msg}` : msg
        }
        return String(item)
      })
      .join('; ')
  }
  if (detail && typeof detail === 'object') {
    try {
      return JSON.stringify(detail)
    } catch {
      return ''
    }
  }

  // Otros formatos comunes
  if (typeof obj.message === 'string' && obj.message) return obj.message
  if (typeof obj.error === 'string' && obj.error) return obj.error

  return ''
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
    const message = extractDetail(data) || 'Request failed'
    throw new ApiError(res.status, message, data)
  }

  // 204 No Content no tiene body para parsear
  if (res.status === 204) {
    return undefined as T
  }

  return res.json() as Promise<T>
}
