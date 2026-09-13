import { useEffect, useState } from 'react'
import {
  ElicitationState,
  getElicitationState,
  sendElicitationMessage,
} from '../api/elicitation'
import { ApprovalPanel } from './ApprovalPanel'

interface ElicitationPanelProps {
  projectId: number
  phaseReady: boolean
  onPhaseReady: () => void
}

export function ElicitationPanel({ projectId, phaseReady, onPhaseReady }: ElicitationPanelProps) {
  const [state, setState] = useState<ElicitationState | null>(null)
  const [answer, setAnswer] = useState('')
  const [loading, setLoading] = useState(true)
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    getElicitationState(projectId)
      .then((data) => {
        if (!cancelled) setState(data)
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Error al cargar la elicitación')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [projectId])

  const handleStart = async () => {
    setError('')
    setSending(true)
    try {
      const data = await sendElicitationMessage(projectId)
      setState(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error al iniciar la elicitación')
    } finally {
      setSending(false)
    }
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!answer.trim() || sending) return
    setError('')
    setSending(true)
    try {
      const data = await sendElicitationMessage(projectId, answer.trim())
      setState(data)
      setAnswer('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error al enviar la respuesta')
    } finally {
      setSending(false)
    }
  }

  if (loading) {
    return (
      <div className="flex justify-center py-8">
        <div className="h-6 w-6 animate-spin rounded-full border-b-2 border-blue-600"></div>
      </div>
    )
  }

  if (!state) {
    return error ? <div className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</div> : null
  }

  if (state.done && state.resumen) {
    if (phaseReady) {
      return (
        <div className="rounded-lg border border-green-200 bg-green-50 p-4 text-center">
          <p className="font-medium text-gray-900">✓ Resumen aprobado</p>
          <p className="mt-1 text-sm text-gray-600">
            Usa el botón "Avanzar fase" arriba para continuar con la propuesta.
          </p>
        </div>
      )
    }

    return (
      <ApprovalPanel
        projectId={projectId}
        resumen={state.resumen}
        onDecided={(result) => {
          if (result.decision === 'approve') {
            onPhaseReady()
          } else {
            getElicitationState(projectId).then(setState).catch(() => {})
          }
        }}
      />
    )
  }

  const hasStarted = state.history.length > 0 || state.question !== null

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-2 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-900">
        <span>ℹ️</span>
        <span>Voy a hacerte preguntas para entender tu proyecto</span>
      </div>

      {state.history.map((item, index) => (
        <div key={index} className="flex flex-col gap-2">
          <div className="flex justify-start">
            <div className="max-w-[70%] rounded-lg bg-blue-50 px-4 py-2 text-sm text-gray-900">
              {item.pregunta}
            </div>
          </div>
          <div className="flex justify-end">
            <div className="max-w-[70%] rounded-lg border border-gray-200 bg-white px-4 py-2 text-sm text-gray-900">
              {item.respuesta}
            </div>
          </div>
        </div>
      ))}

      {state.question && (
        <div className="flex justify-start">
          <div className="max-w-[70%] rounded-lg bg-blue-50 px-4 py-2 text-sm text-gray-900">
            {state.question}
          </div>
        </div>
      )}

      {!hasStarted ? (
        <div className="flex justify-center py-4">
          <button
            type="button"
            onClick={handleStart}
            disabled={sending}
            className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            Comenzar elicitación
          </button>
        </div>
      ) : (
        <form onSubmit={handleSubmit} className="mt-2 flex gap-2">
          <input
            type="text"
            value={answer}
            onChange={(e) => setAnswer(e.target.value)}
            placeholder="Escribe tu respuesta..."
            disabled={sending}
            className="flex-1 rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-2 focus:ring-blue-500 disabled:bg-gray-100"
          />
          <button
            type="submit"
            disabled={sending || !answer.trim()}
            className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            Enviar
          </button>
        </form>
      )}

      {error && <p className="text-sm text-red-700">{error}</p>}
    </div>
  )
}
