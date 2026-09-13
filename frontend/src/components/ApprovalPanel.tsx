import { useState } from 'react'
import { decideElicitation, ElicitationDecisionResult } from '../api/elicitation'

interface ApprovalPanelProps {
  projectId: number
  resumen: Record<string, unknown>
  onDecided: (result: ElicitationDecisionResult) => void
}

function formatResumenValue(value: unknown): string {
  if (value == null) return '—'
  if (typeof value === 'string') return value
  if (Array.isArray(value)) return value.join(', ')
  return JSON.stringify(value)
}

export function ApprovalPanel({ projectId, resumen, onDecided }: ApprovalPanelProps) {
  const [mode, setMode] = useState<'idle' | 'modify'>('idle')
  const [feedback, setFeedback] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const runDecision = async (decision: 'approve' | 'modify' | 'reject', decisionFeedback?: string) => {
    setError('')
    setLoading(true)
    try {
      const result = await decideElicitation(projectId, decision, decisionFeedback)
      onDecided(result)
      setMode('idle')
      setFeedback('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error al registrar la decisión')
    } finally {
      setLoading(false)
    }
  }

  const handleReject = () => {
    if (!window.confirm('¿Seguro que quieres rechazar y reiniciar esta fase? Se perderá el progreso actual.')) {
      return
    }
    runDecision('reject')
  }

  const handleModifySubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!feedback.trim()) return
    runDecision('modify', feedback.trim())
  }

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4">
      <h2 className="font-semibold text-gray-900">Resumen del proyecto</h2>
      <dl className="mt-3 grid grid-cols-1 gap-x-6 gap-y-2 sm:grid-cols-2">
        {Object.entries(resumen).map(([key, value]) => (
          <div key={key}>
            <dt className="text-xs uppercase tracking-wide text-gray-500">{key}</dt>
            <dd className="text-sm text-gray-900">{formatResumenValue(value)}</dd>
          </div>
        ))}
      </dl>

      <div className="mt-4 rounded-lg border border-green-200 bg-green-50 p-4">
        <p className="text-center font-medium text-gray-900">¿Apruebas este resumen?</p>

        {mode === 'idle' && (
          <div className="mt-3 flex flex-wrap justify-center gap-2">
            <button
              type="button"
              disabled={loading}
              onClick={() => runDecision('approve')}
              className="rounded-lg border border-green-600 bg-white px-4 py-2 text-sm font-medium text-green-700 hover:bg-green-100 disabled:opacity-50"
            >
              ✓ Aprobar
            </button>
            <button
              type="button"
              disabled={loading}
              onClick={() => setMode('modify')}
              className="rounded-lg border border-blue-600 bg-white px-4 py-2 text-sm font-medium text-blue-700 hover:bg-blue-50 disabled:opacity-50"
            >
              ✎ Solicitar cambios
            </button>
            <button
              type="button"
              disabled={loading}
              onClick={handleReject}
              className="rounded-lg border border-red-600 bg-white px-4 py-2 text-sm font-medium text-red-700 hover:bg-red-50 disabled:opacity-50"
            >
              ✕ Rechazar y reiniciar
            </button>
          </div>
        )}

        {mode === 'modify' && (
          <form onSubmit={handleModifySubmit} className="mt-3 space-y-2">
            <textarea
              value={feedback}
              onChange={(e) => setFeedback(e.target.value)}
              placeholder="Describe qué te gustaría cambiar..."
              rows={3}
              disabled={loading}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-2 focus:ring-blue-500 disabled:bg-gray-100"
            />
            <div className="flex justify-end gap-2">
              <button
                type="button"
                disabled={loading}
                onClick={() => {
                  setMode('idle')
                  setFeedback('')
                }}
                className="rounded-lg px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-100"
              >
                Cancelar
              </button>
              <button
                type="submit"
                disabled={loading || !feedback.trim()}
                className="rounded-lg bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
              >
                Enviar cambios
              </button>
            </div>
          </form>
        )}

        {error && <p className="mt-2 text-center text-sm text-red-700">{error}</p>}
      </div>
    </div>
  )
}
