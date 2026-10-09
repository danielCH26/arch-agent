import { afterEach, describe, expect, it } from 'vitest'
import { getThemePreference, setThemePreference } from '../theme'
import { setMediaMatches } from '../test/setup'

const isDark = () => document.documentElement.classList.contains('dark')

describe('theme', () => {
  afterEach(() => {
    localStorage.clear()
    document.documentElement.classList.remove('dark')
  })

  it('usa "system" por defecto o si el valor guardado no es válido', () => {
    expect(getThemePreference()).toBe('system')
    localStorage.setItem('archagent-theme', 'violeta')
    expect(getThemePreference()).toBe('system')
  })

  it('guarda la preferencia y aplica la clase dark', () => {
    setThemePreference('dark')
    expect(localStorage.getItem('archagent-theme')).toBe('dark')
    expect(isDark()).toBe(true)

    setThemePreference('light')
    expect(isDark()).toBe(false)
  })

  it('con "system" sigue la preferencia del sistema operativo', () => {
    setMediaMatches({ '(prefers-color-scheme: dark)': true })
    setThemePreference('system')
    expect(isDark()).toBe(true)

    setMediaMatches({ '(prefers-color-scheme: dark)': false })
    setThemePreference('system')
    expect(isDark()).toBe(false)
  })
})
