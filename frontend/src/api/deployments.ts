import { apiFetch } from './client'

export interface CloudProvider {
  id: string
  name: string
  short_name: string
  color: string
  docs_url: string
  service_count: number
}

/** Un componente de la arquitectura y el servicio donde se despliega. */
export interface MappedComponent {
  component: string
  service_id: string
  service_name: string
  category: string
  category_label: string
  summary: string
  deploy_note: string
  // Término del catálogo que disparó el mapeo; se muestra para poder
  // explicar por qué cayó en ese servicio.
  matched_term: string
}

/** Servicio que no sale de un componente: lo agrega el proveedor para unir
 *  dos piezas que en esa nube no se conectan directamente. */
export interface BridgeService {
  service_id: string
  service_name: string
  category: string
  category_label: string
  deploy_note: string
}

export interface DeploymentPlan {
  provider: { id: string; name: string; short_name: string; color: string; docs_url: string }
  components: MappedComponent[]
  connections: { from: string; to: string }[]
  bridges: BridgeService[]
  unmapped: string[]
  dropped_connections: { from: string; to: string }[]
  attachment_id: string | null
  url: string | null
  // Presente cuando el mapeo salió pero la imagen no se pudo renderizar.
  render_error: string | null
}

export interface DeploymentVersion {
  message_id: number
  id: string
  url: string
  provider: string | null
  created_at: string
  decision: 'approve' | 'modify' | 'reject' | null
}

export function listCloudProviders(): Promise<{ providers: CloudProvider[] }> {
  return apiFetch<{ providers: CloudProvider[] }>('/api/deployments/providers')
}

export function generateDeployment(projectId: number, provider: string): Promise<DeploymentPlan> {
  return apiFetch<DeploymentPlan>('/api/deployments/generate', {
    method: 'POST',
    body: JSON.stringify({ project_id: projectId, provider }),
  })
}

export function fetchDeploymentHistory(projectId: number): Promise<DeploymentVersion[]> {
  return apiFetch<{ deployments: DeploymentVersion[] }>(
    `/api/deployments/history?project_id=${encodeURIComponent(String(projectId))}`,
  ).then((data) => data.deployments ?? [])
}

export function decideDeployment(
  projectId: number,
  attachmentId: string,
  decision: 'approve' | 'modify' | 'reject',
  feedback?: string,
): Promise<{ decision: string; message: string }> {
  return apiFetch<{ decision: string; message: string }>('/api/deployments/decision', {
    method: 'POST',
    body: JSON.stringify({
      project_id: projectId,
      attachment_id: attachmentId,
      decision,
      ...(feedback ? { feedback } : {}),
    }),
  })
}
