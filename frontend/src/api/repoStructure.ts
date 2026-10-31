import { apiFetch } from './client'

/** Una línea del árbol, con la fuente que la respalda. */
export interface StructureLine {
  path: string
  note: string
  /** "convencion" = la trae el stack; "patron" = la aporta un patrón. */
  origin: 'convencion' | 'patron'
  pattern_name: string
  role: string
  module: string
  source_title: string
  source_url: string
}

/** Patrón elegido para un módulo, con por qué y dónde queda. */
export interface ModulePattern {
  pattern_name: string
  role: string
  justification: string
  matched_kind: string
  source_title: string
  source_url: string
  path: string
  /** false = aplica, pero la convención del stack no documenta dónde ponerlo. */
  placed: boolean
}

export interface DetectedModule {
  name: string
  kind: string
  /** Término que decidió el tipo; vacío si fue el valor por omisión. */
  matched_term: string
  origin: 'diagrama' | 'propuesta'
  uncovered_reason: string
  patterns: ModulePattern[]
}

export interface ConventionSummary {
  convention_id: string
  name: string
  summary: string
  matched_term: string
  nesting_limit: number | null
  fuentes: { titulo: string; url: string }[]
}

export interface StructurePlan {
  attachment_id: string | null
  backend: ConventionSummary | null
  frontend: ConventionSummary | null
  modules: DetectedModule[]
  lines: StructureLine[]
  tree_text: string
  warnings: string[]
  unmatched_layers: string[]
  module_kinds: string[]
}

export interface StructureVersion {
  message_id: number
  id: string
  created_at: string
  backend_name: string | null
  frontend_name: string | null
  module_count: number
  tree_text: string
  plan: Partial<StructurePlan>
}

export function generateRepoStructure(projectId: number): Promise<StructurePlan> {
  return apiFetch<StructurePlan>('/api/repo-structure/generate', {
    method: 'POST',
    body: JSON.stringify({ project_id: projectId }),
  })
}

export function fetchRepoStructureHistory(projectId: number): Promise<StructureVersion[]> {
  return apiFetch<{ structures: StructureVersion[] }>(
    `/api/repo-structure/history?project_id=${encodeURIComponent(String(projectId))}`,
  ).then((data) => data.structures ?? [])
}
