import { apiFetch } from './client'

export interface Pattern {
  id: number
  pattern_name: string
  category: string | null
  description: string | null
  use_cases: string | null
  // Curado desde data/patterns/*.yaml; normalmente { ventajas: string[], desventajas: string[] }.
  tradeoffs: Record<string, unknown> | null
  when_not_to_use: string | null
  // Imagen ilustrativa: ruta servida por el front (/pattern-images/...) o URL. Null si el patrón aún no tiene.
  image?: string | null
  image_alt?: string | null
  image_source?: PatternImageSource | null
}

/** Atribución de la imagen del patrón (campo `image_source` del YAML). */
export interface PatternImageSource {
  titulo?: string | null
  autor?: string | null
  licencia?: string | null
  url?: string | null
  // true si la imagen se adaptó (fondo, márgenes...): el pie dice "adaptada", como exige CC BY.
  modificada?: boolean | null
}

export interface PatternList {
  total: number
  items: Pattern[]
}

export interface PatternSourceChunk {
  id: number
  chunk_type: string
  chunk_text: string
  chunk_metadata: { filename?: string; source_type?: string; [key: string]: unknown } | null
}

/** HU8: detalle del patrón citado, destino de "Verificar fuente" (por `pattern_id`) en una propuesta. */
export interface PatternDetail extends Pattern {
  decision_signals: unknown[] | null
  chunks: { id: number; chunk_type: string; chunk_text: string; source: string }[]
}

export function getPatternDetail(patternId: number) {
  return apiFetch<PatternDetail>(`/api/patterns/${patternId}`)
}

export function listPatterns(limit = 200, offset = 0) {
  return apiFetch<PatternList>(`/api/patterns?limit=${limit}&offset=${offset}`)
}

// Catálogo cacheado por sesión: la propuesta y el ADR lo usan para mostrar la
// imagen del patrón elegido sin pedir el detalle (con chunks) de cada uno.
let catalog: Promise<Map<number, Pattern>> | null = null

/** Patrones del catálogo por id. Si falla, la próxima llamada lo vuelve a pedir. */
export function getPatternCatalog(): Promise<Map<number, Pattern>> {
  if (!catalog) {
    catalog = listPatterns()
      .then((list) => new Map(list.items.map((pattern) => [pattern.id, pattern])))
      .catch((error) => {
        catalog = null
        throw error
      })
  }
  return catalog
}

export function listPatternSourceChunks(patternId: number) {
  return apiFetch<PatternSourceChunk[]>(`/api/patterns/${patternId}/source-chunks`)
}
