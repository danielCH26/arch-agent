import { useState } from 'react'
import type { Phase, Decision } from '../../api/approvals'
import { PhaseFeedbackComposer } from './PhaseFeedbackComposer'

interface PhaseActionsProps {
  phase: Phase
  currentDecision: Decision | null
  onApprove: () => Promise<void>
  onModify: (feedback: string, payload?: Record<string, unknown>) => Promise<void>
  onReject: (feedback: string) => Promise<void>
  disabled?: boolean
  /**
   * HU11 (REQ-SA-25 / design §F.1): ``mode='past'`` is rendered when the
   * user clicked Editar on a past-phase row of <PhaseHistory>. It hides
   * Aprobar/Rechazar (the prior approval stays intact — HU11 AC literal
   * compliance) and shows an inline banner clarifying the current phase.
   * Default ``'current'`` preserves the HU10 button layout.
   */
  mode?: 'current' | 'past'
  /**
   * HU11: the project's actual current phase, used in the past-mode banner
   * to disambiguate "you're editing a prior phase" from the live one.
   */
  currentPhase?: Phase
}

/**
 * Per-phase Aprobar / Modificar / Rechazar button group.
 *
 * Mount condition (REQ-SA-19/20): <ChatWindow> renders this component
 * whenever ``approvalsStore.pendingDecision[currentPhase]`` is non-null.
 * The component is intentionally phase-agnostic: it renders three buttons
 * for prose phases and two (Aprobar / Rechazar) for ``final`` per
 * REQ-SA-8.
 *
 * Click handlers fire POSTs immediately for approve / reject; modify
 * opens <PhaseFeedbackComposer> inline to capture the feedback string.
 *
 * HU11: in ``mode='past'`` the Aprobar/Rechazar buttons are hidden and a
 * banner makes the user's intent explicit. Phase stays modifiable.
 */
export function PhaseActions({
  phase,
  currentDecision,
  onApprove,
  onModify,
  onReject,
  disabled,
  mode = 'current',
  currentPhase,
}: PhaseActionsProps) {
  const [composerOpen, setComposerOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const wrap = (label: string, fn: () => Promise<void>) => async () => {
    if (disabled || busy) return
    setBusy(true)
    setError(null)
    try {
      await fn()
    } catch (err) {
      setError(err instanceof Error ? err.message : `${label} failed`)
    } finally {
      setBusy(false)
    }
  }

  const handleApprove = wrap('Aprobar', onApprove)

  const handleRejectClick = () => {
    // Lightweight confirm: the dedicated rejection composer is out of scope
    // for HU10 (the spec only requires ``action: 'reject'`` is POSTable;
    // a richer reject-feedback flow is a follow-up). For now the user gets
    // an inline confirm dialog.
    const reason = window.prompt('¿Por qué rechazas esta fase? (opcional)')
    void wrap('Rechazar', async () => {
      await onReject(reason ?? '')
    })()
  }

  const handleModify = async (
    feedback: string,
    payload?: Record<string, unknown>,
  ) => {
    await wrap('Modificar', async () => {
      await onModify(feedback, payload)
      setComposerOpen(false)
    })()
  }

  const showModify = phase !== 'final'
  const isPast = mode === 'past'

  return (
    <div
      className="flex flex-col gap-2 p-3 bg-white border border-gray-200 rounded-lg shadow-sm"
      data-testid={`phase-actions-${phase}`}
      aria-busy={busy}
      data-phase-mode={mode}
    >
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium text-gray-700">
          Decisión para la fase: <strong>{phase}</strong>
        </span>
        {currentDecision && (
          <span
            className="text-xs text-gray-500"
            data-testid={`phase-actions-decision-${phase}`}
          >
            Última decisión: {currentDecision.action} (
            {currentDecision.decided_at?.slice(0, 10) ?? '—'})
          </span>
        )}
      </div>

      {isPast && (
        <div
          className="text-xs px-2 py-1 bg-amber-50 text-amber-800 border border-amber-200 rounded"
          data-testid={`phase-actions-past-banner-${phase}`}
          role="status"
        >
          Estás editando una fase anterior ({phase}). La fase actual sigue
          siendo {currentPhase ?? 'desconocida'}. Las fases posteriores
          marcadas con ⚠ están aprobadas pero pueden estar desactualizadas.
        </div>
      )}

      <div className="flex gap-2">
        {!isPast && (
          <button
            type="button"
            onClick={handleApprove}
            disabled={disabled || busy}
            className="flex-1 px-4 py-2 bg-green-600 text rounded hover:bg-green-700 disabled:bg-green-300"
            data-testid={`phase-actions-approve-${phase}`}
          >
            Aprobar
          </button>
        )}

        {showModify && (
          <button
            type="button"
            onClick={() => setComposerOpen(true)}
            disabled={disabled || busy}
            className={
              isPast
                ? 'flex-1 px-4 py-2 bg-yellow-500 text-white rounded hover:bg-yellow-600 disabled:bg-yellow-300'
                : 'flex-1 px-4 py-2 bg-yellow-500 text-white rounded hover:bg-yellow-600 disabled:bg-yellow-300'
            }
            data-testid={`phase-actions-modify-${phase}`}
          >
            {isPast ? 'Regenerar' : 'Modificar'}
          </button>
        )}

        {!isPast && (
          <button
            type="button"
            onClick={handleRejectClick}
            disabled={disabled || busy}
            className="flex-1 px-4 py-2 bg-red-600 text-white rounded hover:bg-red-700 disabled:bg-red-300"
            data-testid={`phase-actions-reject-${phase}`}
          >
            Rechazar
          </button>
        )}
      </div>

      {error && (
        <div
          className="text-sm text-red-700 bg-red-50 p-2 rounded"
          role="alert"
          data-testid={`phase-actions-error-${phase}`}
        >
          {error}
        </div>
      )}

      {composerOpen && showModify && (
        <PhaseFeedbackComposer
          phase={phase}
          currentPhase={currentPhase}
          onSubmit={handleModify}
          onCancel={() => setComposerOpen(false)}
        />
      )}
    </div>
  )
}