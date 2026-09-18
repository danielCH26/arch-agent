import { apiFetch } from './client'

export interface DiagramVersion {
  message_id: number
  url: string
  filename: string | null
  created_at: string
}

/**
 * HU6: antes esto devolvia [] ante CUALQUIER error (401, 404, 500), asi que
 * un proyecto ajeno o un backend caido se veian exactamente igual que un
 * proyecto sin diagramas. Ahora lanza y el panel decide que mostrar.
 *
 * Antes usaba `fetch` directo (bypass de `apiFetch`), asi que un 401 no
 * disparaba el logout/redirect automatico del cliente compartido.
 */
export async function fetchDiagramHistory(projectId: number): Promise<DiagramVersion[]> {
  const payload = await apiFetch<{ diagrams?: DiagramVersion[] }>(
    `/api/diagrams/history?project_id=${encodeURIComponent(String(projectId))}`,
  )
  return Array.isArray(payload.diagrams) ? payload.diagrams : []
}

/**
 * HU6: antes se ignoraba el status de la respuesta, asi que un 400/404 del
 * backend quedaba invisible y la UI marcaba la decision como exitosa igual.
 *
 * Antes usaba `fetch` directo (bypass de `apiFetch`), asi que un 401 no
 * disparaba el logout/redirect automatico del cliente compartido.
 */
export async function submitDiagramDecision(
  projectId: number,
  decision: 'approve' | 'modify' | 'reject',
  feedback?: string,
): Promise<void> {
  await apiFetch<void>(
    `/api/diagrams/decision?project_id=${encodeURIComponent(String(projectId))}`,
    {
      method: 'POST',
      body: JSON.stringify({ decision, feedback }),
    },
  )
}