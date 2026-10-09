import { apiFetch } from './client'

export type DiagramDecision = 'approve' | 'modify' | 'reject'

export interface DiagramVersion {
  message_id: number
  id: string
  url: string
  filename: string | null
  created_at: string
  decision: DiagramDecision | null
}

export async function fetchDiagramHistory(projectId: number): Promise<DiagramVersion[]> {
  const payload = await apiFetch<{ diagrams?: DiagramVersion[] }>(
    `/api/diagrams/history?project_id=${encodeURIComponent(String(projectId))}`,
  )
  return Array.isArray(payload.diagrams) ? payload.diagrams : []
}

export async function submitDiagramDecision(
  projectId: number,
  decision: DiagramDecision,
  feedback?: string,
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
