import { authStore } from '../stores/authStore'

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
 */
export async function fetchDiagramHistory(projectId: number): Promise<DiagramVersion[]> {
  const token = authStore.getState().token

  const response = await fetch(
    `/api/diagrams/history?project_id=${encodeURIComponent(String(projectId))}`,
    {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    },
  )

  if (!response.ok) {
    throw new Error(await readErrorDetail(response, 'No se pudo cargar el historial de diagramas.'))
  }

  const payload = (await response.json()) as { diagrams?: DiagramVersion[] }
  return Array.isArray(payload.diagrams) ? payload.diagrams : []
}

/**
 * HU6: antes se ignoraba el status de la respuesta, asi que un 400/404 del
 * backend quedaba invisible y la UI marcaba la decision como exitosa igual.
 */
export async function submitDiagramDecision(
  projectId: number,
  decision: 'approve' | 'modify' | 'reject',
  feedback?: string,
): Promise<void> {
  const token = authStore.getState().token
  const response = await fetch(
    `/api/diagrams/decision?project_id=${encodeURIComponent(String(projectId))}`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ decision, feedback }),
    },
  )

  if (!response.ok) {
    throw new Error(await readErrorDetail(response, 'No se pudo registrar la decision.'))
  }
}

async function readErrorDetail(response: Response, fallback: string): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown }
    if (typeof body.detail === 'string' && body.detail.trim()) return body.detail
  } catch {
    // respuesta sin JSON (504 de nginx, HTML de error, etc.)
  }
  return `${fallback} (HTTP ${response.status})`
}