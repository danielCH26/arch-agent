import { authStore } from '../stores/authStore'

const BASE_URL = import.meta.env.VITE_API_BASE_URL || ''

/** URL absoluta de un endpoint del backend (respeta VITE_API_BASE_URL). */
export function apiUrl(path: string): string {
  return `${BASE_URL}${path}`
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

/** Sin conexión de red (DevTools → Offline, Wi-Fi caído…). */
export const NETWORK_ERROR_MESSAGE =
  'No se pudo conectar con el servidor. Revisa tu conexión e inténtalo de nuevo.'

/** El proxy (nginx) responde, pero el backend no está disponible. */
export const SERVER_UNAVAILABLE_MESSAGE =
  'El servidor no está disponible en este momento. Inténtalo de nuevo en unos minutos.'

const SERVER_ERROR_MESSAGE = 'Ocurrió un error en el servidor. Inténtalo de nuevo en unos minutos.'
const UNEXPECTED_ERROR_MESSAGE = 'Ocurrió un error inesperado. Inténtalo de nuevo.'

export const STATUS_MESSAGES: Record<number, string> = {
  400: 'La solicitud no es válida. Revisa los datos e inténtalo de nuevo.',
  401: 'Tu sesión expiró. Inicia sesión de nuevo.',
  403: 'No tienes permiso para realizar esta acción.',
  404: 'No se encontró lo que buscabas.',
  405: 'Esta acción no está disponible.',
  408: 'El servidor tardó demasiado en responder. Inténtalo de nuevo.',
  409: 'La acción no se pudo completar por un conflicto con el estado actual. Recarga la página e inténtalo de nuevo.',
  413: 'El archivo es demasiado grande.',
  415: 'El tipo de archivo no es compatible.',
  422: 'Algunos datos no son válidos. Revísalos e inténtalo de nuevo.',
  429: 'Hiciste demasiadas solicitudes seguidas. Espera un momento e inténtalo de nuevo.',
  502: SERVER_UNAVAILABLE_MESSAGE,
  503: SERVER_UNAVAILABLE_MESSAGE,
  504: SERVER_UNAVAILABLE_MESSAGE,
}

// `detail` genéricos que FastAPI/Starlette generan en inglés (p. ej. una ruta
// inexistente responde {"detail": "Not Found"}): se reemplazan por el mensaje
// del código de estado.
const FRAMEWORK_DETAILS = new Set([
  'bad request',
  'unauthorized',
  'forbidden',
  'not found',
  'method not allowed',
  'request timeout',
  'conflict',
  'payload too large',
  'request entity too large',
  'unsupported media type',
  'unprocessable entity',
  'unprocessable content',
  'too many requests',
  'internal server error',
  'bad gateway',
  'service unavailable',
  'gateway timeout',
])

function statusMessage(status: number): string {
  if (STATUS_MESSAGES[status]) return STATUS_MESSAGES[status]
  return status >= 500 ? SERVER_ERROR_MESSAGE : UNEXPECTED_ERROR_MESSAGE
}

/**
 * Convierte la respuesta de error del backend en un mensaje para el usuario.
 * FastAPI devuelve `detail` como string (errores propios, ya en español) o,
 * en errores de validación (422), como una lista de objetos en inglés.
 */
export function errorMessageFromResponse(status: number, data: unknown): string {
  const detail = (data as { detail?: unknown } | null)?.detail
  if (typeof detail === 'string' && detail.trim() && !FRAMEWORK_DETAILS.has(detail.trim().toLowerCase())) {
    return detail
  }

  if (Array.isArray(detail) && detail.length > 0) {
    const fields = detail
      .map((item) => (item as { loc?: unknown[] })?.loc?.slice(-1)[0])
      .filter((field): field is string => typeof field === 'string')
    const base = STATUS_MESSAGES[422]
    return fields.length ? `${base} Campos: ${[...new Set(fields)].join(', ')}.` : base
  }

  return statusMessage(status)
}

/**
 * Mensaje para el usuario a partir del payload de un evento SSE `error`, que
 * puede llegar como texto o como objeto ({message} / {detail}).
 */
export function streamErrorMessage(payload: unknown, fallback = UNEXPECTED_ERROR_MESSAGE): string {
  if (typeof payload === 'string' && payload.trim()) return payload
  if (payload && typeof payload === 'object') {
    const { message, detail, error } = payload as Record<string, unknown>
    for (const value of [message, detail, error]) {
      if (typeof value === 'string' && value.trim()) return value
    }
  }
  return fallback
}

/**
 * Sesión inválida o expirada: limpia el estado y vuelve al login. Lo usan
 * todas las llamadas al backend (fetch, streams SSE y subidas por XHR).
 */
export function handleUnauthorized(): ApiError {
  void authStore.getState().logout()
  // replace: no deja la página protegida en el historial.
  window.location.replace('/login')
  return new ApiError(401, STATUS_MESSAGES[401])
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

  const res = await safeFetch(apiUrl(path), {
    ...options,
    headers,
  })

  if (res.status === 401) {
    throw handleUnauthorized()
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
