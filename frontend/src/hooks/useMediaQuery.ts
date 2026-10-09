import { useEffect, useState } from 'react'

/** true mientras la media query se cumple (se actualiza al cambiar). */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() => window.matchMedia?.(query).matches ?? false)

  useEffect(() => {
    const media = window.matchMedia?.(query)
    if (!media) return
    const onChange = () => setMatches(media.matches)
    onChange()
    media.addEventListener?.('change', onChange)
    // Respaldo: algunos entornos (p. ej. emulación de dispositivos) no
    // disparan `change` al redimensionar.
    window.addEventListener('resize', onChange)
    return () => {
      media.removeEventListener?.('change', onChange)
      window.removeEventListener('resize', onChange)
    }
  }, [query])

  return matches
}
