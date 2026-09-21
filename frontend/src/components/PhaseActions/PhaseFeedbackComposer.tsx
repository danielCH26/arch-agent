import { useState } from 'react'
import type { Phase } from '../../api/approvals'

interface PhaseFeedbackComposerProps {
  phase: Phase
  initialPayload?: Record<string, unknown>
  onSubmit: (feedback: string, payload?: Record<string, unknown>) => Promise<void>
  onCancel: () => void
}

/**
 * Inline composer for the Modify action.
 *
 * For ``revision`` (REQ-SA-7) the composer exposes structured fields for
 * ``patron_elegido``, ``ventajas``, ``desventajas``. For prose phases the
 * composer is a single textarea + submit. The output is the
 * ``{feedback, payload}`` shape the generic decision endpoint expects
 * (REQ-SA-14).
 */
export function PhaseFeedbackComposer({
  phase,
  initialPayload,
  onSubmit,
  onCancel,
}: PhaseFeedbackComposerProps) {
  const [feedback, setFeedback] = useState('')
  const [patron, setPatron] = useState<string>(
    typeof initialPayload?.['patron_elegido'] === 'string'
      ? (initialPayload['patron_elegido'] as string)
      : '',
  )
  const [ventajas, setVentajas] = useState<string>(
    Array.isArray(initialPayload?.['ventajas'])
      ? (initialPayload['ventajas'] as string[]).join('\n')
      : '',
  )
  const [desventajas, setDesventajas] = useState<string>(
    Array.isArray(initialPayload?.['desventajas'])
      ? (initialPayload['desventajas'] as string[]).join('\n')
      : '',
  )
  const [busy, setBusy] = useState(false)

  const isRevision = phase === 'revision'

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!feedback.trim() && !isRevision) return
    setBusy(true)
    try {
      if (isRevision) {
        await onSubmit(feedback, {
          patron_elegido: patron,
          ventajas: ventajas.split('\n').map((s) => s.trim()).filter(Boolean),
          desventajas: desventajas
            .split('\n')
            .map((s) => s.trim())
            .filter(Boolean),
        })
      } else {
        await onSubmit(feedback)
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="flex flex-col gap-2 p-3 bg-gray-50 border border-gray-200 rounded"
      data-testid={`phase-feedback-composer-${phase}`}
    >
      {isRevision && (
        <>
          <label className="text-sm font-medium text-gray-700">
            Patrón elegido
            <input
              type="text"
              value={patron}
              onChange={(e) => setPatron(e.target.value)}
              className="mt-1 block w-full p-2 border border-gray-300 rounded"
              data-testid={`phase-feedback-composer-patron-${phase}`}
            />
          </label>
          <label className="text-sm font-medium text-gray-700">
            Ventajas (una por línea)
            <textarea
              value={ventajas}
              onChange={(e) => setVentajas(e.target.value)}
              className="mt-1 block w-full p-2 border border-gray-300 rounded"
              rows={3}
              data-testid={`phase-feedback-composer-ventajas-${phase}`}
            />
          </label>
          <label className="text-sm font-medium text-gray-700">
            Desventajas (una por línea)
            <textarea
              value={desventajas}
              onChange={(e) => setDesventajas(e.target.value)}
              className="mt-1 block w-full p-2 border border-gray-300 rounded"
              rows={3}
              data-testid={`phase-feedback-composer-desventajas-${phase}`}
            />
          </label>
        </>
      )}

      <label className="text-sm font-medium text-gray-700">
        Comentario (feedback)
        <textarea
          value={feedback}
          onChange={(e) => setFeedback(e.target.value)}
          required
          className="mt-1 block w-full p-2 border border-gray-300 rounded"
          rows={3}
          data-testid={`phase-feedback-composer-feedback-${phase}`}
        />
      </label>

      <div className="flex gap-2">
        <button
          type="submit"
          disabled={busy || !feedback.trim()}
          className="flex-1 px-4 py-2 bg-yellow-500 text-white rounded hover:bg-yellow-600 disabled:bg-yellow-300"
          data-testid={`phase-feedback-composer-submit-${phase}`}
        >
          Enviar
        </button>
        <button
          type="button"
          onClick={onCancel}
          disabled={busy}
          className="flex-1 px-4 py-2 bg-gray-300 text-gray-800 rounded hover:bg-gray-400 disabled:bg-gray-200"
          data-testid={`phase-feedback-composer-cancel-${phase}`}
        >
          Cancelar
        </button>
      </div>
    </form>
  )
}