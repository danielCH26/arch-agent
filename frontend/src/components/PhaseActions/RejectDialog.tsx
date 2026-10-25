/**
 * HU10 v2 inline reject-confirmation dialog (REQ-SA-32).
 *
 * Closes PR #78 important finding: ``window.prompt`` returning ``null``
 * was treated as a reject confirmation. The inline dialog gives the
 * user explicit Cancel and Confirm buttons; Cancel MUST NOT fire any
 * network request.
 */

import { useState } from 'react'

export interface RejectDialogProps {
  open: boolean
  phase: string
  busy: boolean
  onCancel: () => void
  onConfirm: (feedback: string) => void
}

export function RejectDialog({
  open,
  phase,
  busy,
  onCancel,
  onConfirm,
}: RejectDialogProps) {
  const [feedback, setFeedback] = useState('')

  if (!open) return null

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="reject-dialog-title"
      data-testid="reject-dialog"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
    >
      <div className="w-full max-w-md rounded-lg bg-white p-6 shadow-xl">
        <h3
          id="reject-dialog-title"
          className="text-lg font-semibold text-gray-900"
        >
          Rechazar {phase}
        </h3>
        <p className="mt-2 text-sm text-gray-600">
          Indicale al asistente qué debe ajustar. Esta acción registra una
          decisión de rechazo en el historial.
        </p>
        <label className="mt-4 block text-sm font-medium text-gray-700">
          Motivo del rechazo
          <textarea
            data-testid="reject-feedback"
            value={feedback}
            onChange={(event) => setFeedback(event.target.value)}
            rows={3}
            className="mt-1 w-full rounded border border-gray-300 p-2 text-sm text-gray-900"
            placeholder="Describe qué debe cambiarse..."
          />
        </label>
        <div className="mt-6 flex justify-end gap-2">
          <button
            type="button"
            data-testid="reject-cancel"
            disabled={busy}
            onClick={onCancel}
            className="rounded border border-gray-300 px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
          >
            Cancelar
          </button>
          <button
            type="button"
            data-testid="reject-confirm"
            disabled={busy}
            onClick={() => onConfirm(feedback.trim())}
            className="rounded bg-red-600 px-3 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50"
          >
            Confirmar rechazo
          </button>
        </div>
      </div>
    </div>
  )
}