/**
 * HU10 v2 `<PhaseActions>` -- Aprobar / Modificar / Rechazar surface.
 *
 * Reads the pending decision from `useApprovalsStore` and renders one
 * button per available action. Closes PR #78 findings:
 *   * Aprobar is an outlined button (green border and text), like Rechazar:
 *     el verde sólido con texto blanco pesaba demasiado en la pantalla.
 *   * Reject opens the inline `<RejectDialog>` -- never `window.prompt`.
 *   * Calls the typed `decidePhase` client; 409 responses surface as
 *     `ApiConflictError` (REQ-SA-29, REQ-SA-34).
 *
 * Also includes "Avanzar" button when phaseReady=true (REQ-SA-23/24).
 *
 * On `propuesta` the decision lives in <ProposalCard>/<ProposalActions>
 * (it owns the proposal lifecycle, the `engram_state` snapshot and the
 * reject->revert). There this component is mounted with `hideDecision` and
 * renders ONLY "Avanzar", so the two surfaces can never disagree.
 */

import { useState } from 'react'
import {
  ApiConflictError,
  type PhaseDecisionAction,
} from '../../api/approvals'
import { advancePhase } from '../../api/projects'
import { useApprovalsStore } from '../../stores/approvalsStore'
import { useProjectsStore } from '../../stores/projectsStore'
import { RejectDialog } from './RejectDialog'

export interface PhaseActionsProps {
  projectId: number
  phase: string
  /** Hide the Modificar button on `final` (REQ-SA-8). */
  allowModify?: boolean
  /** Show "Avanzar" button when phase is ready to advance */
  phaseReady?: boolean
  /**
   * Hide Aprobar / Modificar / Rechazar (keep only "Avanzar"). Used on
   * `propuesta`, where <ProposalCard> is the single decision surface.
   */
  hideDecision?: boolean
  /**
   * Se llama tras una decisión o un avance exitoso, para que la página
   * (ChatPage) recargue su propio estado de fase (stepper, barra superior).
   */
  onPhaseChanged?: () => void | Promise<void>
}

const ACTIONS: Array<{ action: PhaseDecisionAction; label: string; testId: string }> = [
  { action: 'approve', label: 'Aprobar', testId: 'phase-action-approve' },
  { action: 'modify', label: 'Modificar', testId: 'phase-action-modify' },
]

export function PhaseActions({
  projectId,
  phase,
  allowModify = true,
  phaseReady = false,
  hideDecision = false,
  onPhaseChanged,
}: PhaseActionsProps) {
  const decide = useApprovalsStore((s) => s.decide)
  const refreshApprovals = useApprovalsStore((s) => s.refresh)
  const storedPending = useApprovalsStore((s) => s.pendingByPhase[phase] ?? null)
  const pending = hideDecision ? null : storedPending
  const errorMessage = useApprovalsStore((s) => s.error)
  const clearError = useApprovalsStore((s) => s.clearError)
  const getProject = useProjectsStore((s) => s.getProject)

  const [busy, setBusy] = useState(false)
  const [modifyFeedback, setModifyFeedback] = useState('')
  const [showModify, setShowModify] = useState(false)
  const [showReject, setShowReject] = useState(false)
  const [advancing, setAdvancing] = useState(false)
  const [advanceError, setAdvanceError] = useState<string | null>(null)

  async function handle(action: PhaseDecisionAction, feedback?: string) {
    if (action === 'modify' && !feedback?.trim()) {
      setShowModify(true)
      return
    }
    setBusy(true)
    try {
      await decide(projectId, phase, {
        action,
        feedback: feedback?.trim() || null,
      })
      setShowModify(false)
      setShowReject(false)
      setModifyFeedback('')
      void Promise.resolve(onPhaseChanged?.()).catch(() => undefined)
    } catch (err) {
      // 409 surfaces as ApiConflictError; the store already records the
      // typed error. We let the parent render the banner.
      if (!(err instanceof ApiConflictError)) {
        // eslint-disable-next-line no-console
        console.error('PhaseActions.decide failed', err)
      }
    } finally {
      setBusy(false)
    }
    // B3 (Soomri round-2 re-review): refresh the project right after a
    // decision so `phase_ready` flips in the store and the Avanzar
    // button appears immediately after Aprobar (mirror of the
    // handleAdvance refresh below).
    void getProject(projectId).catch(() => undefined)
  }

  async function handleAdvance() {
    setAdvancing(true)
    setAdvanceError(null)
    try {
      await advancePhase(projectId)
      // Refresh project state to show new phase
      await getProject(projectId)
      // The new phase has its own pending decision. `pendingByPhase` only
      // holds the phase that was current at the last fetch, so without this
      // re-fetch the new phase showed no Aprobar/Modificar/Rechazar until
      // the next chat message or a reload.
      await refreshApprovals()
      void Promise.resolve(onPhaseChanged?.()).catch(() => undefined)
    } catch (err) {
      // eslint-disable-next-line no-console
      console.error('PhaseActions.advance failed', err)
      // Surface the failure in the UI instead of only logging it.
      setAdvanceError(
        err instanceof Error && err.message
          ? err.message
          : 'No se pudo avanzar de fase. Inténtalo de nuevo.',
      )
    } finally {
      setAdvancing(false)
    }
  }

  const showAdvance = phaseReady && phase !== 'requerimientos' && phase !== 'final'

  if (!pending && !showAdvance) {
    // No pending decision and nothing to advance: do not render the
    // surface (REQ-SA-19.2). B3 (Soomri round-2 re-review): an approved
    // phase has pending=null under the inverted pending_decision
    // semantics -- the old `if (!pending) return null` unmounted the
    // Avanzar button exactly when it was the only way forward.
    return null
  }

  return (
    <div
      data-testid="phase-actions"
      className="mt-3 flex flex-col gap-2 rounded-lg border border-blue-200 bg-blue-50 p-4 text-sm text-blue-900"
    >
      {pending && (
        <p className="font-medium">
          Decisión pendiente para la fase{' '}
          <span className="font-bold">{phase}</span>
          {pending.since && (
            <span className="ml-2 text-xs text-blue-700">
              desde {new Date(pending.since).toLocaleString()}
            </span>
          )}
        </p>
      )}

      {advanceError && (
        <div
          role="alert"
          data-testid="phase-actions-advance-error"
          className="rounded bg-red-50 px-3 py-2 text-xs text-red-700"
        >
          {advanceError}
          <button
            type="button"
            onClick={() => setAdvanceError(null)}
            className="ml-2 underline"
          >
            Cerrar
          </button>
        </div>
      )}

      {errorMessage && (
        <div
          role="alert"
          data-testid="phase-actions-error"
          className="rounded bg-red-50 px-3 py-2 text-xs text-red-700"
        >
          {errorMessage}
          <button
            type="button"
            onClick={clearError}
            className="ml-2 underline"
          >
            Cerrar
          </button>
        </div>
      )}

      <div className="flex flex-wrap gap-2">
        {pending &&
          ACTIONS.filter((a) => allowModify || a.action !== 'modify').map((a) => (
          <button
            key={a.action}
            type="button"
            disabled={busy}
            data-testid={a.testId}
            onClick={() => void handle(a.action)}
            className={
              a.action === 'approve'
                // Mismo tratamiento que Rechazar: borde y letra del color de
                // la acción, sin relleno. El verde sólido llamaba más la
                // atención que el contenido que hay que revisar.
                ? 'rounded border border-green-300 px-3 py-2 font-medium text-green-700 hover:bg-green-50 disabled:opacity-50'
                : 'rounded border border-blue-600 px-3 py-2 font-medium text-blue-700 hover:bg-blue-100 disabled:opacity-50'
            }
          >
            {a.label}
          </button>
        ))}

        {showAdvance && (
          <button
            type="button"
            disabled={advancing}
            data-testid="phase-action-advance"
            onClick={() => void handleAdvance()}
            className="rounded bg-indigo-600 px-3 py-2 font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
          >
            {advancing ? 'Avanzando...' : 'Avanzar'}
          </button>
        )}
        {pending && (
          <button
            type="button"
            disabled={busy}
            data-testid="phase-action-reject"
            onClick={() => setShowReject(true)}
            className="rounded border border-red-300 px-3 py-2 font-medium text-red-700 hover:bg-red-50 disabled:opacity-50"
          >
            Rechazar
          </button>
        )}
      </div>

      {showModify && (
        <div className="mt-2 space-y-2">
          <label className="block font-medium" htmlFor={`modify-feedback-${phase}`}>
            ¿Qué debe ajustarse?
          </label>
          <textarea
            id={`modify-feedback-${phase}`}
            data-testid="modify-feedback"
            value={modifyFeedback}
            onChange={(event) => setModifyFeedback(event.target.value)}
            rows={3}
            className="w-full rounded border border-blue-200 p-2 text-gray-900"
            placeholder="Describe los cambios..."
          />
          <button
            type="button"
            disabled={busy || !modifyFeedback.trim()}
            data-testid="modify-submit"
            onClick={() => void handle('modify', modifyFeedback)}
            className="rounded bg-blue-600 px-3 py-2 text-white hover:bg-blue-700 disabled:opacity-50"
          >
            Enviar ajuste
          </button>
        </div>
      )}

      <RejectDialog
        open={showReject}
        phase={phase}
        busy={busy}
        onCancel={() => setShowReject(false)}
        onConfirm={(feedback) => void handle('reject', feedback)}
      />
    </div>
  )
}