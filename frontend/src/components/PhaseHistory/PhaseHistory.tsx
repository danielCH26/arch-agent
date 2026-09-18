import { useMemo } from 'react'
import type { Phase, PhaseStatusItem } from '../../api/approvals'

interface PhaseHistoryProps {
  phases: PhaseStatusItem[]
  currentPhase: Phase | null
  onEdit: (phase: Phase) => void
}

/**
 * HU11 (REQ-SA-26): per-phase audit panel rendered below the chat
 * messages. One row per phase in the canonical order; each row carries a
 * status badge, the last-decision summary, an optional yellow ⚠ stale
 * badge, and an ``Editar`` button for past phases (hidden for the
 * active phase and for ``final`` per REQ-SA-8).
 *
 * The Editar button wires into ``approvalsStore.setPending(pastPhase)``
 * — the typed action that HU10 added but never called. Clicking it
 * mounts ``<PhaseActions mode='past'>`` for that phase (T8).
 */
export function PhaseHistory({ phases, currentPhase, onEdit }: PhaseHistoryProps) {
  const ordered = useMemo(() => phases ?? [], [phases])

  if (ordered.length === 0) {
    return (
      <div
        className="text-xs text-gray-400 px-3 py-2"
        data-testid="phase-history-empty"
      >
        Cargando historial…
      </div>
    )
  }

  return (
    <div
      className="flex flex-col gap-1 p-3 bg-gray-50 border border-gray-200 rounded-lg"
      data-testid="phase-history"
      aria-label="Historial por fase"
    >
      <div className="text-xs font-semibold text-gray-600 mb-1">
        Historial por fase
      </div>
      {ordered.map((phase) => (
        <PhaseHistoryRow
          key={phase.name}
          item={phase}
          isCurrent={phase.name === currentPhase}
          onEdit={onEdit}
        />
      ))}
    </div>
  )
}

interface PhaseHistoryRowProps {
  item: PhaseStatusItem
  isCurrent: boolean
  onEdit: (phase: Phase) => void
}

function PhaseHistoryRow({ item, isCurrent, onEdit }: PhaseHistoryRowProps) {
  const { name, label, status, current_decision, stale } = item
  // Editar button is hidden for the active phase (user is already in
  // PhaseActions for it) and for ``final`` (REQ-SA-8 — Modify disabled).
  const showEdit = !isCurrent && name !== 'final'

  return (
    <div
      className="flex items-center justify-between gap-2 px-2 py-1 rounded hover:bg-white"
      data-testid={`phase-history-row-${name}`}
    >
      <div className="flex items-center gap-2 min-w-0">
        <StatusBadge status={status} />
        <span className="text-sm text-gray-700 truncate">{label}</span>
        {current_decision && (
          <span
            className="text-xs text-gray-400 truncate"
            data-testid={`phase-history-decision-${name}`}
          >
            ({current_decision.action}
            {current_decision.decided_at
              ? ` · ${current_decision.decided_at.slice(0, 10)}`
              : ''}
            )
          </span>
        )}
        {stale && (
          <span
            className="text-xs px-1.5 py-0.5 bg-yellow-100 text-yellow-800 rounded"
            data-testid={`phase-history-stale-${name}`}
            title="Puedes re-aprobar para refrescar"
            aria-label="stale"
          >
            ⚠ stale
          </span>
        )}
      </div>
      {showEdit && (
        <button
          type="button"
          onClick={() => onEdit(name)}
          className="text-xs px-2 py-1 bg-blue-50 text-blue-700 rounded hover:bg-blue-100"
          data-testid={`phase-history-edit-${name}`}
        >
          Editar
        </button>
      )}
    </div>
  )
}

function StatusBadge({ status }: { status: 'active' | 'approved' | 'pending' }) {
  const styles: Record<typeof status, string> = {
    active: 'bg-blue-100 text-blue-800',
    approved: 'bg-green-100 text-green-800',
    pending: 'bg-gray-100 text-gray-700',
  }
  const labels: Record<typeof status, string> = {
    active: 'activa',
    approved: 'aprobada',
    pending: 'pendiente',
  }
  return (
    <span
      className={`text-xs px-1.5 py-0.5 rounded ${styles[status]}`}
      data-testid={`phase-history-status-${status}`}
    >
      {labels[status]}
    </span>
  )
}