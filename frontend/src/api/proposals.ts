import { authStore } from '../stores/authStore'
import { apiFetch } from './client'

export interface ProposalCitation {
  pattern_id: number | null
  pattern_name: string | null
  similarity: number | null
  snippet?: string | null
}

export type ProposalLifecycle = 'proposed' | 'approved' | 'rejected'
export type ProposalDecision = 'approve' | 'reject'

export interface ProposalOut {
  id: number
  project_id: number
  iteration: number
  content: string
  citations: ProposalCitation[]
  feedback: string | null
  lifecycle: ProposalLifecycle
  created_at: string
}

export interface ProjectProposalState {
  approved: boolean
  approved_at: string | null
  approval_id: number | null
  proposal_snapshot_chars: number
  last_decision: string | null
}

export interface ProjectProposalDecisionResponse {
  decision: 'approve' | 'modify' | 'reject'
  phase_ready: boolean
  approval_id: number | null
  proposal_snapshot_chars: number
  message: string
}

export interface ProposalDecisionResponse {
  proposal_id: number
  lifecycle: 'approved' | 'rejected'
  current_phase: string | null
  phase_ready: boolean
}

interface ProposalStreamCallbacks {
  onToken: (token: string) => void
  onSources: (citations: ProposalCitation[]) => void
  onDone: (proposalId: number, citations: ProposalCitation[]) => void
  onError: (message: string) => void
}

function parseEvent(rawEvent: string, callbacks: ProposalStreamCallbacks): boolean {
  let name = 'message'
  const data: string[] = []
  for (const line of rawEvent.split('\n')) {
    if (line.startsWith('event:')) name = line.slice(6).trim()
    if (line.startsWith('data:')) data.push(line.slice(5).trim())
  }
  const payload = data.join('\n')

  if (name === 'sources') {
    try { callbacks.onSources(JSON.parse(payload) as ProposalCitation[]) } catch { callbacks.onSources([]) }
    return false
  }
  if (name === 'token' && payload) {
    try {
      const parsed = JSON.parse(payload)
      callbacks.onToken(parsed.delta || parsed)
    } catch { callbacks.onToken(payload) }
    return false
  }
  if (name === 'done') {
    try {
      const parsed = JSON.parse(payload) as { proposal_id: number; citations?: ProposalCitation[] }
      callbacks.onDone(parsed.proposal_id, parsed.citations ?? [])
    } catch { callbacks.onError('La propuesta terminó con un formato inválido.') }
    return true
  }
  if (name === 'error') {
    try { callbacks.onError(JSON.parse(payload)) } catch { callbacks.onError(payload || 'No se pudo generar la propuesta.') }
    return true
  }
  return false
}

export function createProposalStream(
  mode: 'generate' | 'modify',
  payload: { projectId: number; proposalId?: number; feedback?: string },
  callbacks: ProposalStreamCallbacks,
): () => void {
  const controller = new AbortController()
  const token = authStore.getState().token
  const url = mode === 'generate'
    ? '/api/proposals/generate'
    : `/api/proposals/${payload.proposalId}/modify`
  const body = mode === 'generate'
    ? { project_id: payload.projectId }
    : { feedback: payload.feedback }

  void (async () => {
    try {
      const response = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        body: JSON.stringify(body),
        signal: controller.signal,
      })
      if (response.status === 401) {
        authStore.getState().logout()
        window.location.replace('/login')
        return
      }
      if (!response.ok) {
        const error = await response.json().catch(() => ({}))
        callbacks.onError((error.detail as string) || 'No se pudo generar la propuesta.')
        return
      }
      if (!response.body) {
        callbacks.onError('El servidor no entregó contenido para la propuesta.')
        return
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const events = buffer.split(/\r?\n\r?\n/)
        buffer = events.pop() || ''
        for (const event of events) {
          if (event.trim() && parseEvent(event, callbacks)) return
        }
      }
      if (buffer.trim() && parseEvent(buffer, callbacks)) return
      callbacks.onError('La generación terminó antes de completarse.')
    } catch (error) {
      if (error instanceof Error && error.name === 'AbortError') return
      callbacks.onError(error instanceof Error ? error.message : 'No se pudo conectar con el servidor.')
    }
  })()

  return () => controller.abort()
}

export function decideProposal(proposalId: number, decision: ProposalDecision, comment?: string) {
  return apiFetch<ProposalDecisionResponse>(`/api/proposals/${proposalId}/decide`, {
    method: 'POST',
    body: JSON.stringify({ decision, comment }),
  })
}

export function getProposal(proposalId: number) {
  return apiFetch<ProposalOut>(`/api/proposals/${proposalId}`)
}

export function getProjectProposalState(projectId: number) {
  return apiFetch<ProjectProposalState>(`/api/projects/${projectId}/proposal`)
}

export function decideProjectProposal(
  projectId: number,
  decision: 'approve' | 'modify' | 'reject',
  options: { feedback?: string; proposalText?: string } = {},
) {
  return apiFetch<ProjectProposalDecisionResponse>(`/api/projects/${projectId}/proposal/decision`, {
    method: 'POST',
    body: JSON.stringify({ decision, feedback: options.feedback, proposal_text: options.proposalText }),
  })
}
