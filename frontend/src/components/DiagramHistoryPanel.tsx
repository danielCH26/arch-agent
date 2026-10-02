import { useEffect, useState } from 'react'
import { fetchDiagramHistory, type DiagramDecision, type DiagramVersion } from '../api/diagrams'
import { useDialog } from '../hooks/useDialog'
import { formatDateTime } from '../lib/format'

interface DiagramHistoryPanelProps {
  projectId: number
  open: boolean
  onClose: () => void
}

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

export function DiagramHistoryPanel({ projectId, open, onClose }: DiagramHistoryPanelProps) {
  const [diagrams, setDiagrams] = useState<DiagramVersion[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const dialogRef = useDialog<HTMLElement>({ open, onClose })

  useEffect(() => {
    if (!open) return
    // Se descartan los datos y las respuestas de un proyecto anterior.
    let cancelled = false
    setDiagrams([])
    setLoading(true)
    setError('')
    fetchDiagramHistory(projectId)
      .then((data) => {
        if (!cancelled) setDiagrams(data)
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : 'No se pudo cargar el historial.')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [open, projectId])

  if (!open) return null

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
            <h2 id="diagram-history-title" className="text-lg font-semibold text-gray-900">Historial de diagramas</h2>
            <p className="mt-1 text-sm text-gray-500">Versiones generadas para este proyecto.</p>
          </div>
          <button type="button" onClick={onClose} className="rounded p-2 text-gray-500 hover:bg-gray-100 hover:text-gray-800" aria-label="Cerrar historial">✕</button>
        </div>

        {loading && <div className="flex justify-center py-10"><div className="h-6 w-6 animate-spin rounded-full border-2 border-sky-200 border-b-sky-600" /></div>}
        {!loading && error && <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</p>}
        {!loading && !error && diagrams.length === 0 && <p className="py-8 text-center text-sm text-gray-500">Todavía no hay diagramas generados.</p>}

        <div className="space-y-4">
          {diagrams.map((diagram) => (
            <article key={diagram.id} className="rounded-xl border border-gray-200 p-3">
              <img src={diagram.url} alt={diagram.filename ?? `Diagrama ${diagram.message_id}`} className="w-full rounded-lg bg-gray-50" loading="lazy" />
              <div className="mt-3 flex items-center justify-between gap-2">
                <span className="text-xs text-gray-500">{formatDateTime(diagram.created_at)}</span>
                <span className={`rounded-full px-2 py-1 text-xs font-medium ${diagram.decision ? styles[diagram.decision] : 'bg-gray-100 text-gray-600'}`}>
                  {diagram.decision ? labels[diagram.decision] : 'Sin decisión'}
                </span>
              </div>
            </article>
          ))}
        </div>
      </section>
    </div>
  )
}
