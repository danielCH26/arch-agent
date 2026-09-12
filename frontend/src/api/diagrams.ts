import { authStore } from '../stores/authStore'

export interface DiagramVersion {
  message_id: number
  url: string
  filename: string | null
  created_at: string
}

export async function fetchDiagramHistory(projectId: number): Promise<DiagramVersion[]> {
  const token = authStore.getState().token

  const response = await fetch(
    `/api/diagrams/history?project_id=${encodeURIComponent(String(projectId))}`,
    {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    },
  )

  if (!response.ok) {
    return []
  }

  const payload = (await response.json()) as { diagrams?: DiagramVersion[] }
  return Array.isArray(payload.diagrams) ? payload.diagrams : []
}

export async function submitDiagramDecision(
  projectId: number,
  decision: 'approve' | 'modify' | 'reject',
  feedback?: string,
): Promise<void> {
  const token = authStore.getState().token
  await fetch(`/api/diagrams/decision?project_id=${encodeURIComponent(String(projectId))}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ decision, feedback }),
  })
}