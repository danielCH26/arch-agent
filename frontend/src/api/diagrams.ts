import { apiFetch } from './client'

export type DiagramDecision = 'approve' | 'modify' | 'reject'

export interface DiagramVersion {
  message_id: number
  // UUID del adjunto: identidad del diagrama para las decisiones.
  id: string
  url: string
  filename: string | null
  created_at: string
  // Ultima decision registrada sobre ESTE diagrama; null = sin decidir.
  decision: DiagramDecision | null
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
  decision: DiagramDecision,
  feedback?: string,
  // UUID del diagrama (Attachment.id) sobre el que se decide. Con el la
  // decision queda guardada POR diagrama y sobrevive a un F5; sin el (cliente
  // viejo) solo se registra a nivel de proyecto.
  attachmentId?: string,
): Promise<void> {
  await apiFetch<void>(
    `/api/diagrams/decision?project_id=${encodeURIComponent(String(projectId))}`,
    {
      method: 'POST',
      body: JSON.stringify({ decision, feedback, attachment_id: attachmentId }),
    },
  )
}