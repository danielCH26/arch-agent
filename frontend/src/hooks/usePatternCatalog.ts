import { useEffect, useState } from 'react'
import { getPatternCatalog, type Pattern } from '../api/patterns'

/**
 * Patrones del catálogo por id (imagen, alt y atribución incluidos), o null
 * mientras carga o si falló. Sin catálogo la vista sigue sin imágenes.
 */
export function usePatternCatalog(enabled = true): Map<number, Pattern> | null {
  const [catalog, setCatalog] = useState<Map<number, Pattern> | null>(null)

  useEffect(() => {
    if (!enabled) return
    let cancelled = false
    getPatternCatalog()
      .then((map) => {
        if (!cancelled) setCatalog(map)
      })
      .catch(() => undefined)
    return () => {
      cancelled = true
    }
  }, [enabled])

  return catalog
}
