import { describe, expect, it } from 'vitest'
import { displayProjectName } from '../format'

describe('displayProjectName', () => {
  it('pone mayúscula inicial y las siglas en mayúsculas', () => {
    expect(displayProjectName('prueba adr')).toBe('Prueba ADR')
    expect(displayProjectName('adr')).toBe('ADR')
    expect(displayProjectName('agenda con api de pagos')).toBe('Agenda con API de pagos')
  })

  it('solo cambia palabras completas', () => {
    expect(displayProjectName('padre')).toBe('Padre')
    expect(displayProjectName('Clínica Ápice')).toBe('Clínica Ápice')
  })
})
