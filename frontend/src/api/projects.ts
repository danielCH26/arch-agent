import { apiFetch } from './client'

export interface Project {
  id: number
  name: string
  description: string | null
  current_phase: string | null
  phase_ready: boolean
  created_at: string
}

export interface ProjectCreate {
  name: string
  description?: string
}

export interface PhaseInfo {
  current_phase: string
  phase_ready: boolean
  available_phases: string[]
}

export interface PhaseAdvanceResponse {
  current_phase: string
  phase_ready: boolean
  message: string
}

export async function listProjects(): Promise<Project[]> {
  return apiFetch<Project[]>('/api/projects')
}

export async function getProject(projectId: number): Promise<Project> {
  return apiFetch<Project>(`/api/projects/${projectId}`)
}

export async function createProject(data: ProjectCreate): Promise<Project> {
  return apiFetch<Project>('/api/projects', {
    method: 'POST',
    body: JSON.stringify(data),
  })
}

export async function deleteProject(projectId: number): Promise<void> {
  await apiFetch<void>(`/api/projects/${projectId}`, {
    method: 'DELETE',
  })
}

export async function getProjectPhase(projectId: number): Promise<PhaseInfo> {
  return apiFetch<PhaseInfo>(`/api/projects/${projectId}/phase`)
}

export async function advancePhase(projectId: number): Promise<PhaseAdvanceResponse> {
  return apiFetch<PhaseAdvanceResponse>(`/api/projects/${projectId}/advance`, {
    method: 'POST',
  })
}

export async function markReady(projectId: number): Promise<{ phase_ready: boolean; message: string }> {
  return apiFetch<{ phase_ready: boolean; message: string }>(`/api/projects/${projectId}/mark-ready`, {
    method: 'POST',
  })
}
