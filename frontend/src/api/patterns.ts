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

export function listPatterns(limit = 200, offset = 0) {
  return apiFetch<PatternList>(`/api/patterns?limit=${limit}&offset=${offset}`)
}

export function listPatternSourceChunks(patternId: number) {
  return apiFetch<PatternSourceChunk[]>(`/api/patterns/${patternId}/source-chunks`)
}
