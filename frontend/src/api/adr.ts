import { apiFetch } from './client'

export interface AdrOut {
  markdown: string | null
  generated_at: string | null
  // false cuando la guía práctica (sección 7) no se pudo redactar con el LLM.
  guide_complete: boolean
  // Cambios pedidos al revisar el ADR, en orden.
  feedback_history: string[]
  // Momento en que se aprobó el ADR (proyecto terminado), o null.
  approved_at: string | null
  // Avisos de la revisión automática de la guía (cifras o tecnologías que no
  // salen de lo decidido). Opcional: los ADR guardados antes no lo traen.
  guide_warnings?: string[]
  // Adjunto del diagrama que usa el ADR, para mostrar esa misma imagen.
  diagram_attachment_id?: string | null
}

const adrPath = (projectId: number) => `/api/projects/${encodeURIComponent(String(projectId))}/adr`

export function getAdr(projectId: number): Promise<AdrOut> {
  return apiFetch<AdrOut>(adrPath(projectId))
}

// Sin feedback regenera el ADR; con feedback registra los cambios pedidos y los aplica.
export function generateAdr(projectId: number, feedback?: string): Promise<AdrOut> {
  return apiFetch<AdrOut>(adrPath(projectId), {
    method: 'POST',
    body: JSON.stringify(feedback ? { feedback } : {}),
  })
}

// Aprueba el ADR: el proyecto queda terminado.
export function approveAdr(projectId: number): Promise<AdrOut> {
  return apiFetch<AdrOut>(`${adrPath(projectId)}/approve`, { method: 'POST' })
}
