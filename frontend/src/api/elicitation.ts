import { apiFetch } from './client'

export interface ElicitationHistoryItem {
  pregunta: string
  respuesta: string
}

export interface ElicitationState {
  done: boolean
  question: string | null
  resumen: Record<string, unknown> | null
  history: ElicitationHistoryItem[]
}

export type ElicitationDecision = 'approve' | 'modify' | 'reject'

export interface ElicitationDecisionResult {
  decision: string
  phase_ready: boolean
  message: string
}

export async function getElicitationState(projectId: number): Promise<ElicitationState> {
  return apiFetch<ElicitationState>(`/api/projects/${projectId}/elicitation`)
}

export async function sendElicitationMessage(
  projectId: number,
  answer?: string
): Promise<ElicitationState> {
  return apiFetch<ElicitationState>(`/api/projects/${projectId}/elicitation/message`, {
    method: 'POST',
    body: JSON.stringify({ answer }),
  })
}

export async function decideElicitation(
  projectId: number,
  decision: ElicitationDecision,
  feedback?: string
): Promise<ElicitationDecisionResult> {
  return apiFetch<ElicitationDecisionResult>(`/api/projects/${projectId}/elicitation/decision`, {
    method: 'POST',
    body: JSON.stringify({ decision, feedback }),
  })
}
