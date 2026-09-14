import { useState } from 'react'
import { proposalsStore } from '../../stores/proposalsStore'

interface ProposalActionsProps {
  proposalId: number
  /** Disables the buttons once the user has already approved/rejected. */
  disabled?: boolean
}

/**
 * Approve / Modify / Reject action panel mounted inside the ProposalCard.
 *
 * Each click dispatches the corresponding action on `proposalsStore`:
 *   - Aprobar   -> decide('approve')
 *   - Modificar -> opens a composer; submit fires modify()
 *   - Rechazar  -> decide('reject')
 *
 * The composer collapses back to a button after submit so the user can keep
 * iterating without the panel eating the screen. Errors from the store are
 * surfaced inline.
 */
export function ProposalActions({ proposalId, disabled }: ProposalActionsProps) {
  const inFlight = proposalsStore((s) => s.inFlight)
  const decide = proposalsStore((s) => s.decide)
  const modify = proposalsStore((s) => s.modify)
  const error = proposalsStore((s) => s.error)

  const [composerOpen, setComposerOpen] = useState(false)
  const [feedback, setFeedback] = useState('')
  const [comment, setComment] = useState('')
  const [localError, setLocalError] = useState<string | null>(null)

  const isBusy = inFlight !== 'idle'

  async function onApprove() {
    setLocalError(null)
    try {
      await decide(proposalId, 'approve', comment.trim() || undefined)
      setComment('')
    } catch (err) {
      setLocalError(err instanceof Error ? err.message : 'approve failed')
    }
  }

  async function onReject() {
    setLocalError(null)
    try {
      await decide(proposalId, 'reject', comment.trim() || undefined)
      setComment('')
    } catch (err) {
      setLocalError(err instanceof Error ? err.message : 'reject failed')
    }
  }

  async function onSubmitFeedback() {
    const trimmed = feedback.trim()
    if (!trimmed) {
      setLocalError('Escribe feedback antes de iterar')
      return
    }
    setLocalError(null)
    try {
      await modify(proposalId, trimmed)
      setFeedback('')
      setComposerOpen(false)
    } catch (err) {
      setLocalError(err instanceof Error ? err.message : 'modify failed')
    }
  }

  return (
    <div className="mt-3 border-t border-gray-200 pt-3">
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={onApprove}
          disabled={disabled || isBusy}
          className="rounded bg-green-600 px-3 py-1 text-sm font-semibold text-white hover:bg-green-700 disabled:cursor-not-allowed disabled:opacity-50"
          data-testid="proposal-approve"
        >
          Aprobar
        </button>
        <button
          type="button"
          onClick={() => setComposerOpen((open) => !open)}
          disabled={disabled || isBusy}
          className="rounded bg-blue-600 px-3 py-1 text-sm font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
          data-testid="proposal-modify"
        >
          Modificar
        </button>
        <button
          type="button"
          onClick={onReject}
          disabled={disabled || isBusy}
          className="rounded bg-red-600 px-3 py-1 text-sm font-semibold text-white hover:bg-red-700 disabled:cursor-not-allowed disabled:opacity-50"
          data-testid="proposal-reject"
        >
          Rechazar
        </button>

        <label className="ml-auto flex items-center gap-2 text-xs text-gray-500">
          <span>Comentario:</span>
          <input
            type="text"
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            disabled={disabled || isBusy}
            placeholder="Opcional"
            className="w-40 rounded border border-gray-300 px-2 py-1 text-xs"
            data-testid="proposal-comment"
          />
        </label>
      </div>

      {composerOpen && (
        <div className="mt-2 flex flex-col gap-2" data-testid="proposal-composer">
          <textarea
            value={feedback}
            onChange={(e) => setFeedback(e.target.value)}
            disabled={isBusy}
            placeholder="Describe el cambio que quieres (ej. agregar cache, usar Postgres en vez de Mongo, etc.)"
            className="min-h-[60px] w-full rounded border border-gray-300 px-2 py-1 text-sm"
            data-testid="proposal-feedback"
          />
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => setComposerOpen(false)}
              disabled={isBusy}
              className="rounded border border-gray-300 px-3 py-1 text-xs text-gray-700 hover:bg-gray-50 disabled:opacity-50"
            >
              Cancelar
            </button>
            <button
              type="button"
              onClick={onSubmitFeedback}
              disabled={isBusy}
              className="rounded bg-blue-600 px-3 py-1 text-xs font-semibold text-white hover:bg-blue-700 disabled:opacity-50"
              data-testid="proposal-submit-feedback"
            >
              Iterar propuesta
            </button>
          </div>
        </div>
      )}

      {(localError || error) && (
        <p
          className="mt-2 text-xs text-red-600"
          role="alert"
          data-testid="proposal-actions-error"
        >
          {localError ?? error}
        </p>
      )}
    </div>
  )
}