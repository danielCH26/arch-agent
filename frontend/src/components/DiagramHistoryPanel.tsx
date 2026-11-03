import { useEffect, useState } from 'react'
import { fetchDiagramHistory, type DiagramDecision, type DiagramVersion } from '../api/diagrams'
import { fetchDeploymentHistory, type DeploymentVersion } from '../api/deployments'
import { useDialog } from '../hooks/useDialog'
import { formatDateTime } from '../lib/format'
import { DecisionIcon } from './NavIcons'

interface DiagramHistoryPanelProps {
  projectId: number
  open: boolean
  onClose: () => void
}

// Estado de cada versión, solo informativo. Las decisiones (aprobar /
// rechazar / pedir cambios) se toman únicamente en el chat, cuando se le
// muestra el diagrama al usuario.
const labels: Record<DiagramDecision, string> = {
  approve: 'Aprobado',
  reject: 'Rechazado',
  modify: 'Cambios solicitados',
}

const styles: Record<DiagramDecision, string> = {
  approve: 'bg-green-100 text-green-700',
  reject: 'bg-red-100 text-red-700',
  modify: 'bg-amber-100 text-amber-700',
}

interface VersionCardProps {
  url: string
  alt: string
  createdAt: string
  decision: DiagramDecision | null
  /** Nube del despliegue, cuando la versión es de ese tipo. */
  provider?: string | null
}

function VersionCard({ url, alt, createdAt, decision, provider }: VersionCardProps) {
  return (
    <article className="rounded-xl border border-gray-200 p-3">
      {/* Los diagramas son imágenes claras: van sobre una "hoja" clara
          fija y, en modo oscuro, con el brillo atenuado. */}
      <div className="rounded-lg border border-gray-200 bg-[#f8fafc] p-2">
        <img src={url} alt={alt} className="w-full rounded dark:brightness-90" loading="lazy" />
      </div>
      <div className="mt-3 flex items-center justify-between gap-2">
        <span className="text-xs text-gray-500">
          {formatDateTime(createdAt)}
          {provider ? ` · ${provider.toUpperCase()}` : ''}
        </span>
        <span
          className={`inline-flex items-center gap-1 rounded-full px-2 py-1 text-xs font-medium ${
            decision ? styles[decision] : 'bg-gray-100 text-gray-600'
          }`}
        >
          {decision && <DecisionIcon decision={decision} />}
          {decision ? labels[decision] : 'Sin decisión'}
        </span>
      </div>
    </article>
  )
}

/**
 * Historial de diagramas del proyecto: los de arquitectura (HU6) y los de
 * despliegue en la nube, en secciones separadas.
 *
 * El de despliegue también vive aquí, y no solo dentro del panel de
 * Refinamiento, porque ese panel desaparece al avanzar: desde Revisión en
 * adelante las versiones quedaban inalcanzables. Este botón, en cambio,
 * sigue visible. Son dos diagramas distintos del mismo proyecto, así que
 * van en secciones con su encabezado y no mezclados en una lista.
 */
export function DiagramHistoryPanel({ projectId, open, onClose }: DiagramHistoryPanelProps) {
  const [diagrams, setDiagrams] = useState<DiagramVersion[]>([])
  const [deployments, setDeployments] = useState<DeploymentVersion[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const dialogRef = useDialog<HTMLElement>({ open, onClose })

  useEffect(() => {
    if (!open) return
    // Se descartan los datos y las respuestas de un proyecto anterior.
    let cancelled = false
    setDiagrams([])
    setDeployments([])
    setLoading(true)
    setError('')

    // Las dos historias se piden a la vez y por separado: que falle la del
    // despliegue (p. ej. contra un backend sin esa parte todavía) no puede
    // dejar sin ver los diagramas de arquitectura.
    Promise.allSettled([fetchDiagramHistory(projectId), fetchDeploymentHistory(projectId)])
      .then(([arquitectura, despliegue]) => {
        if (cancelled) return
        if (arquitectura.status === 'fulfilled') {
          setDiagrams(arquitectura.value ?? [])
        } else {
          const reason = arquitectura.reason
          setError(
            reason instanceof Error ? reason.message : 'No se pudo cargar el historial.',
          )
        }
        if (despliegue.status === 'fulfilled') {
          setDeployments(despliegue.value ?? [])
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [open, projectId])

  if (!open) return null

  const total = diagrams.length + deployments.length

  return (
    <div
      className="fixed inset-0 z-50 flex justify-end bg-slate-900/30"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <section
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="diagram-history-title"
        className="h-full w-full max-w-md overflow-y-auto bg-white p-5 shadow-2xl"
      >
        <div className="mb-5 flex items-center justify-between">
          <div>
            <h2 id="diagram-history-title" className="text-lg font-semibold text-gray-900">
              Historial de diagramas
            </h2>
            <p className="mt-1 text-sm text-gray-500">Versiones generadas para este proyecto.</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded p-2 text-gray-500 hover:bg-gray-100 hover:text-gray-800"
            aria-label="Cerrar historial"
          >
            ✕
          </button>
        </div>

        {loading && (
          <div className="flex justify-center py-10">
            <div className="h-6 w-6 animate-spin rounded-full border-2 border-sky-200 border-b-sky-600" />
          </div>
        )}
        {!loading && error && (
          <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-700">
            {error}
          </p>
        )}
        {!loading && !error && total === 0 && (
          <p className="py-8 text-center text-sm text-gray-500">
            Todavía no hay diagramas generados en este proyecto.
          </p>
        )}

        {diagrams.length > 0 && (
          <section data-testid="history-architecture" className="mb-6">
            <h3 className="mb-2 text-xs font-bold uppercase tracking-wide text-gray-500">
              Arquitectura
            </h3>
            <div className="space-y-4">
              {diagrams.map((diagram) => (
                <VersionCard
                  key={diagram.id}
                  url={diagram.url}
                  alt={diagram.filename ?? `Diagrama ${diagram.message_id}`}
                  createdAt={diagram.created_at}
                  decision={diagram.decision}
                />
              ))}
            </div>
          </section>
        )}

        {deployments.length > 0 && (
          <section data-testid="history-deployment">
            <h3 className="mb-2 text-xs font-bold uppercase tracking-wide text-gray-500">
              Despliegue en la nube
            </h3>
            <div className="space-y-4">
              {deployments.map((deployment) => (
                <VersionCard
                  key={deployment.id}
                  url={deployment.url}
                  alt={`Diagrama de despliegue ${deployment.provider ?? ''}`.trim()}
                  createdAt={deployment.created_at}
                  decision={deployment.decision}
                  provider={deployment.provider}
                />
              ))}
            </div>
          </section>
        )}

        {total > 0 && (
          <p className="mt-4 border-t border-gray-200 pt-3 text-xs text-gray-500">
            Aquí solo se consulta el historial. Las decisiones sobre un diagrama se toman en el
            chat, cuando se te muestra.
          </p>
        )}
      </section>
    </div>
  )
}
