import { describe, expect, it } from 'vitest'
import {
  errorMessageFromResponse,
  NETWORK_ERROR_MESSAGE,
  safeFetch,
  SERVER_UNAVAILABLE_MESSAGE,
  STATUS_MESSAGES,
  streamErrorMessage,
} from '../client'

describe('errorMessageFromResponse', () => {
  it('usa el detail propio del backend (en español)', () => {
    expect(errorMessageFromResponse(400, { detail: 'El nombre es obligatorio' })).toBe('El nombre es obligatorio')
  })

  it('reemplaza los detail genéricos de FastAPI por el mensaje del código', () => {
    expect(errorMessageFromResponse(404, { detail: 'Not Found' })).toBe(STATUS_MESSAGES[404])
    expect(errorMessageFromResponse(405, { detail: 'Method Not Allowed' })).toBe(STATUS_MESSAGES[405])
    expect(errorMessageFromResponse(500, { detail: 'Internal Server Error' })).toMatch(/error en el servidor/)
  })

  it('resume los errores de validación (422) con los campos', () => {
    const data = {
      detail: [
        { loc: ['body', 'email'], msg: 'value is not a valid email address' },
        { loc: ['body', 'password'], msg: 'String should have at least 6 characters' },
      ],
    }
    expect(errorMessageFromResponse(422, data)).toBe(`${STATUS_MESSAGES[422]} Campos: email, password.`)
  })

  it('trata 502/503/504 (backend caído detrás de nginx) como servidor no disponible', () => {
    for (const status of [502, 503, 504]) {
      expect(errorMessageFromResponse(status, {})).toBe(SERVER_UNAVAILABLE_MESSAGE)
    }
  })

  it('usa mensajes genéricos para códigos sin mensaje propio', () => {
    expect(errorMessageFromResponse(507, null)).toMatch(/error en el servidor/)
    expect(errorMessageFromResponse(418, null)).toMatch(/error inesperado/)
  })
})

describe('streamErrorMessage', () => {
  it('acepta texto, objetos con message/detail y usa el respaldo si no hay texto', () => {
    expect(streamErrorMessage('Falló el modelo')).toBe('Falló el modelo')
    expect(streamErrorMessage({ message: 'Sin cuota' })).toBe('Sin cuota')
    expect(streamErrorMessage({ detail: 'No autorizado' })).toBe('No autorizado')
    expect(streamErrorMessage({ code: 42 }, 'Respaldo')).toBe('Respaldo')
    expect(streamErrorMessage(null, 'Respaldo')).toBe('Respaldo')
  })
})

describe('safeFetch', () => {
  it('traduce un fallo de red a un ApiError en español', async () => {
    global.fetch = () => Promise.reject(new TypeError('Failed to fetch'))
    await expect(safeFetch('/api/x')).rejects.toMatchObject({ status: 0, message: NETWORK_ERROR_MESSAGE })
  })
})
