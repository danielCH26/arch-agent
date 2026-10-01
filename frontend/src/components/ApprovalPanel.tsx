import { useState } from 'react'
import { decideElicitation, ElicitationDecisionResult } from '../api/elicitation'

interface ApprovalPanelProps {
  projectId: number
  resumen: Record<string, unknown>
  onDecided: (result: ElicitationDecisionResult) => void
}

// El LLM a veces devuelve saltos de línea escapados ("\\n" literal) dentro
// de los strings del resumen; los convertimos en saltos reales.
function toLines(text: string): string[] {
  return text
    .replace(/\\n/g, '\n')
    .split(/\r?\n/)
    .map((line) => line.replace(/^\s*[-•*]\s+/, '').trim())
    .filter(Boolean)
}

function resumenItems(value: unknown): string[] {
  if (value == null) return []
  if (Array.isArray(value)) return value.flatMap((item) => resumenItems(item))
  if (typeof value === 'string') return toLines(value)
  if (typeof value === 'object') {
    return Object.entries(value as Record<string, unknown>).map(
      ([key, item]) => `${key}: ${resumenItems(item).join('; ')}`,
    )
  }
  return [String(value)]
}

function ResumenValue({ value }: { value: unknown }) {
  const items = resumenItems(value)
  if (items.length === 0) return <>—</>
  if (items.length === 1) return <>{items[0]}</>
  return (
    <ul className="list-disc space-y-1 pl-5">
      {items.map((item, index) => (
        <li key={index}>{item}</li>
      ))}
    </ul>
  )
}

// Las claves llegan como identificadores ("funcionalidades"); se muestran
// con tildes y como título.
const RESUMEN_LABELS: Record<string, string> = {
  problema: 'Problema',
  usuarios: 'Usuarios',
  funcionalidades: 'Funcionalidades',
  restricciones: 'Restricciones',
  calidad: 'Atributos de calidad',
}

function resumenLabel(key: string): string {
  return RESUMEN_LABELS[key.toLowerCase()] ?? key.replace(/_/g, ' ')
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
      <dl className="mt-3 grid grid-cols-1 gap-x-6 gap-y-4 sm:grid-cols-2">
        {Object.entries(resumen).map(([key, value]) => (
          <div key={key}>
            <dt className="text-base font-bold uppercase tracking-wide text-gray-800">{resumenLabel(key)}</dt>
            <dd className="mt-1 text-sm leading-relaxed text-gray-700"><ResumenValue value={value} /></dd>
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
              aria-label="Cambios que quieres en el resumen"
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
                className="rounded-lg bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 dark:hover:bg-blue-500 disabled:opacity-50"
              >
                Enviar cambios
              </button>
            </div>
          </form>
        )}

        {error && <p role="alert" className="mt-2 text-center text-sm text-red-700">{error}</p>}
      </div>
    </div>
  )
}
