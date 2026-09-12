import { useEffect, useState } from 'react'
import { fetchDiagramHistory, type DiagramVersion } from '../api/diagrams'

interface DiagramHistoryPanelProps {
  projectId: number
  open: boolean
  onClose: () => void
}

export function DiagramHistoryPanel({ projectId, open, onClose }: DiagramHistoryPanelProps) {
  const [versions, setVersions] = useState<DiagramVersion[]>([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!open) return
    setLoading(true)
    fetchDiagramHistory(projectId)
      .then(setVersions)
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

        {!loading && versions.length === 0 && (
          <p className="text-sm text-gray-500">Todavía no hay diagramas generados en este proyecto.</p>
        )}

        <ul className="space-y-4">
          {versions.map((version) => (
            <li key={version.message_id} className="border rounded-lg p-2">
              <img
                src={version.url}
                alt={version.filename ?? `diagrama ${version.message_id}`}
                className="w-full rounded"
                loading="lazy"
              />
              <p className="text-xs text-gray-500 mt-1">
                {new Date(version.created_at).toLocaleString()}
              </p>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}