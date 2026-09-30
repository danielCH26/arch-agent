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

export const NETWORK_ERROR_MESSAGE =
  'No se pudo conectar con el servidor. Revisa tu conexión e inténtalo de nuevo.'

const STATUS_MESSAGES: Record<number, string> = {
  400: 'La solicitud no es válida. Revisa los datos e inténtalo de nuevo.',
  401: 'Tu sesión expiró. Inicia sesión de nuevo.',
  403: 'No tienes permiso para realizar esta acción.',
  404: 'No se encontró lo que buscabas.',
  409: 'La acción no se pudo completar por un conflicto con el estado actual. Recarga la página e inténtalo de nuevo.',
  413: 'El archivo es demasiado grande.',
  422: 'Algunos datos no son válidos. Revísalos e inténtalo de nuevo.',
  429: 'Hiciste demasiadas solicitudes seguidas. Espera un momento e inténtalo de nuevo.',
}

/**
 * Convierte la respuesta de error del backend en un mensaje para el usuario.
 * FastAPI devuelve `detail` como string (errores propios, ya en español) o,
 * en errores de validación (422), como una lista de objetos en inglés.
 */
export function errorMessageFromResponse(status: number, data: unknown): string {
  const detail = (data as { detail?: unknown } | null)?.detail
  if (typeof detail === 'string' && detail.trim()) return detail

  if (Array.isArray(detail) && detail.length > 0) {
    const fields = detail
      .map((item) => (item as { loc?: unknown[] })?.loc?.slice(-1)[0])
      .filter((field): field is string => typeof field === 'string')
    const base = STATUS_MESSAGES[422]
    return fields.length ? `${base} Campos: ${[...new Set(fields)].join(', ')}.` : base
  }

  if (status >= 500) return 'Ocurrió un error en el servidor. Inténtalo de nuevo en unos minutos.'
  return STATUS_MESSAGES[status] ?? 'Ocurrió un error inesperado. Inténtalo de nuevo.'
}

/** `fetch` que traduce los fallos de red (servidor caído, sin conexión). */
export async function safeFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  try {
    return await fetch(input, init)
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') throw err
    throw new ApiError(0, NETWORK_ERROR_MESSAGE)
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

  const res = await safeFetch(`${BASE_URL}${path}`, {
    ...options,
    headers,
  })

  if (res.status === 401) {
    // Token inválido o expirado — limpiar estado y redirigir
    authStore.getState().logout()
    // Redirigir usando replace para no agregar a historial
    window.location.replace('/login')
    throw new ApiError(401, STATUS_MESSAGES[401])
  }

  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new ApiError(res.status, errorMessageFromResponse(res.status, data), data)
  }

  // 204 No Content no tiene body para parsear
  if (res.status === 204) {
    return undefined as T
  }

  return res.json() as Promise<T>
}
