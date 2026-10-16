import { apiFetch } from './client'

export interface AdrOut {
  markdown: string | null
  generated_at: string | null
  // false cuando la guía práctica (sección 7) no se pudo redactar con el LLM.
  guide_complete: boolean
}

export function getAdr(projectId: number): Promise<AdrOut> {
  return apiFetch<AdrOut>(`/api/projects/${encodeURIComponent(String(projectId))}/adr`)
}

export function generateAdr(projectId: number): Promise<AdrOut> {
  return apiFetch<AdrOut>(`/api/projects/${encodeURIComponent(String(projectId))}/adr`, {
    method: 'POST',
  })
}
