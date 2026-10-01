import { useEffect, useState } from 'react'

export type ThemePreference = 'system' | 'light' | 'dark'

// Debe coincidir con el script inline de index.html, que aplica el tema
// antes del primer pintado para evitar un destello claro.
const STORAGE_KEY = 'archagent-theme'
const darkQuery = () => window.matchMedia('(prefers-color-scheme: dark)')

export function getThemePreference(): ThemePreference {
  try {
    const value = localStorage.getItem(STORAGE_KEY)
    if (value === 'light' || value === 'dark' || value === 'system') return value
  } catch {
    // Sin acceso a localStorage: se usa el tema del sistema.
  }
  return 'system'
}

function applyTheme(preference: ThemePreference) {
  const dark = preference === 'dark' || (preference === 'system' && darkQuery().matches)
  document.documentElement.classList.toggle('dark', dark)
}

const listeners = new Set<(preference: ThemePreference) => void>()

export function setThemePreference(preference: ThemePreference) {
  try {
    localStorage.setItem(STORAGE_KEY, preference)
  } catch {
    // La preferencia solo dura esta sesión.
  }
  applyTheme(preference)
  listeners.forEach((listener) => listener(preference))
}

/** Preferencia de tema compartida entre componentes. */
export function useThemePreference(): [ThemePreference, (preference: ThemePreference) => void] {
  const [preference, setPreference] = useState(getThemePreference)

  useEffect(() => {
    listeners.add(setPreference)
    // Con "sistema", seguir los cambios del tema del sistema operativo.
    const query = darkQuery()
    const onSystemChange = () => {
      if (getThemePreference() === 'system') applyTheme('system')
    }
    query.addEventListener('change', onSystemChange)
    return () => {
      listeners.delete(setPreference)
      query.removeEventListener('change', onSystemChange)
    }
  }, [])

  return [preference, setThemePreference]
}
