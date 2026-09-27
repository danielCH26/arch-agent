import { useEffect, useState } from 'react'
import { fetchDiagramHistory, type DiagramDecision, type DiagramVersion } from '../api/diagrams'

interface DiagramHistoryPanelProps {
  projectId: number
  open: boolean
  onClose: () => void
}

// Estado de cada version, solo informativo. Las decisiones (aprobar / rechazar
// / pedir cambios) se toman UNICAMENTE en el chat, cuando se le muestra el
// diagrama al usuario: antes este panel tambien las ofrecia sobre "el diagrama
// actual", asi que se podia rechazar desde aqui algo ya aprobado en el chat.
const STATUS_LABEL: Record<DiagramDecision, { text: string; className: string }> = {
  approve: { text: '✅ Aprobado', className: 'bg-green-100 text-green-800' },
  reject: { text: '❌ Rechazado', className: 'bg-red-100 text-red-800' },
  modify: { text: '✏️ Cambios solicitados', className: 'bg-yellow-100 text-yellow-800' },
}

function StatusBadge({ decision }: { decision: DiagramVersion['decision'] }) {
  const status = decision ? STATUS_LABEL[decision] : null
  return (
    <span
      className={`inline-block text-xs rounded px-2 py-0.5 ${
        status ? status.className : 'bg-gray-100 text-gray-600'
      }`}
    >
      {status ? status.text : 'Sin decisión'}
    </span>
  )
}

export function DiagramHistoryPanel({ projectId, open, onClose }: DiagramHistoryPanelProps) {
  const [versions, setVersions] = useState<DiagramVersion[]>([])
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState('')

  useEffect(() => {
    if (!open) return
    setLoading(true)
    setLoadError('')
    fetchDiagramHistory(projectId)
      .then(setVersions)
      .catch((err) => {
        setVersions([])
        setLoadError(err instanceof Error ? err.message : 'No se pudo cargar el historial.')
      })
      .finally(() => setLoading(false))
  }, [open, projectId])

  if (!open) return null

  return (
    <div className="fixed inset-0 bg-black/40 flex justify-end z-50">
      <div className="w-full max-w-sm bg-white h-full overflow-y-auto p-4 shadow-xl">
        <div className="flex justify-between items-center mb-4">
          <h2 className="text-lg font-semibold">Historial de diagramas</h2>
          <button type="button" onClick={onClose} className="text-gray-500 hover:text-gray-800">
            ✕
          </button>
        </div>

        {loading && <p className="text-sm text-gray-500">Cargando…</p>}

        {!loading && loadError && (
          <p className="text-sm text-red-700 bg-red-50 rounded p-2">{loadError}</p>
        )}

        {!loading && !loadError && versions.length === 0 && (
          <p className="text-sm text-gray-500">Todavía no hay diagramas generados en este proyecto.</p>
        )}

        <ul className="space-y-4">
          {versions.map((version) => (
            <li key={version.id} className="border rounded-lg p-2">
              <img
                src={version.url}
                alt={version.filename ?? `diagrama ${version.message_id}`}
                className="w-full rounded"
                loading="lazy"
              />
              <div className="mt-1 flex items-center justify-between gap-2">
                <p className="text-xs text-gray-500">
                  {new Date(version.created_at).toLocaleString()}
                </p>
                <StatusBadge decision={version.decision} />
              </div>
            </li>
          ))}
        </ul>

        {versions.length > 0 && (
          <p className="mt-4 border-t pt-3 text-xs text-gray-500">
            Aquí solo se consulta el historial. Las decisiones sobre un diagrama se toman en el
            chat, cuando se te muestra.
          </p>
        )}
      </div>
    </div>
  )
}
