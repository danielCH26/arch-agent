import { describe, it, expect } from 'vitest'
import { extractDetail } from './client'

describe('extractDetail', () => {
  it('extrae detail como string simple', () => {
    expect(extractDetail({ detail: 'API key inválida' })).toBe('API key inválida')
  })

  it('extrae detail como string vacia', () => {
    expect(extractDetail({ detail: '' })).toBe('')
  })

  it('extrae detail como array de strings', () => {
    expect(extractDetail({ detail: ['error 1', 'error 2'] })).toBe('error 1; error 2')
  })

  it('extrae detail como array de objetos (FastAPI validation errors)', () => {
    // Formato tipico de FastAPI ValidationError
    expect(
      extractDetail({
        detail: [
          { loc: ['body', 'model'], msg: 'field required', type: 'value_error.missing' },
          { loc: ['body', 'api_key'], msg: 'string too short', type: 'value_error' },
        ],
      })
    ).toBe('body.model: field required; body.api_key: string too short')
  })

  it('extrae detail como objeto (cualquier key:value)', () => {
    // Cuando el backend devuelve algo raro como { detail: { foo: 'bar' } }
    const result = extractDetail({ detail: { foo: 'bar' } })
    expect(result).toContain('"foo"')
    expect(result).toContain('bar')
  })

  it('usa message como fallback si detail no existe', () => {
    expect(extractDetail({ message: 'something failed' })).toBe('something failed')
  })

  it('usa error como fallback si detail ni message existen', () => {
    expect(extractDetail({ error: 'oops' })).toBe('oops')
  })

  it('devuelve string vacia si no hay ningun campo conocido', () => {
    expect(extractDetail({})).toBe('')
    expect(extractDetail(null)).toBe('')
    expect(extractDetail(undefined)).toBe('')
    expect(extractDetail('string')).toBe('')
    expect(extractDetail(123)).toBe('')
  })

  it('nunca devuelve un objeto — proteccion contra [object Object]', () => {
    const casos = [
      { detail: { a: 1 } },
      { detail: [1, 2, 3] },
      { detail: null },
      { detail: { nested: { deep: 'value' } } },
    ]
    for (const c of casos) {
      const r = extractDetail(c)
      expect(typeof r).toBe('string')
      expect(r).not.toBe('[object Object]')
    }
  })
})
