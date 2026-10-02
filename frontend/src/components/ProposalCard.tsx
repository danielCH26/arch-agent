import { useEffect, useState } from 'react'
import { proposalsStore } from '../stores/proposalsStore'
import type { ProposalCitation } from '../api/proposals'
import { renderMarkdownBlocks } from './MessageBubble'
import { formatDateTime } from '../lib/format'

interface ProposalCardProps {
  projectId: number
  onPhaseChanged?: () => void | Promise<void>
}

// Debe coincidir con PROPOSAL_MAX_ITER del backend (default 5).
const MAX_ITERATIONS = 5

const lifecycleStyle = {
  proposed: 'bg-sky-100 text-sky-700',
  approved: 'bg-emerald-100 text-emerald-700',
  rejected: 'bg-red-100 text-red-700',
}

const lifecycleLabel = {
  proposed: 'Pendiente de decisión',
  approved: 'Aprobada',
  rejected: 'Rechazada',
}

export function ProposalCard({ projectId, onPhaseChanged }: ProposalCardProps) {
  const { current, iterations, projectState, activity, error, load, generate, modify, decide, reset } = proposalsStore()
  const [showFeedback, setShowFeedback] = useState(false)
  const [feedback, setFeedback] = useState('')
  const [comment, setComment] = useState('')

  useEffect(() => {
    void load(projectId)
    return () => reset()
  }, [projectId, load, reset])

  const proposal = current?.projectId === projectId ? current : null
  const streaming = activity === 'generating' || activity === 'modifying'
  const busy = activity !== 'idle'
  const approvedWithoutContent = !proposal && projectState?.approved
  const iterationLimitReached = (proposal?.iteration ?? 0) >= MAX_ITERATIONS

  const handleDecision = async (decision: 'approve' | 'reject') => {
    if (!proposal?.id) return
    try {
      await decide(proposal.id, decision, comment.trim() || undefined)
      setComment('')
      setShowFeedback(false)
      await onPhaseChanged?.()
    } catch {
      // El store ya expone el error en la tarjeta.
    }
  }

  const submitModification = () => {
    if (!proposal?.id || !feedback.trim()) return
    modify(proposal.id, feedback.trim())
    setFeedback('')
    setShowFeedback(false)
  }

  return (
    <section className="mb-4 rounded-2xl border border-sky-200 bg-white p-4 shadow-sm" data-testid="proposal-card" aria-labelledby="proposal-title" aria-busy={streaming}>
      {/* Lector de pantalla: estado de la generación, no cada fragmento del texto. */}
      <p className="sr-only" aria-live="polite">
        {streaming
          ? activity === 'modifying' ? 'Generando nueva iteración de la propuesta…' : 'Generando propuesta…'
          : proposal?.id ? `Propuesta, iteración ${proposal.iteration}: ${lifecycleLabel[proposal.lifecycle]}.` : ''}
      </p>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 id="proposal-title" className="text-base font-semibold text-gray-900">
            Propuesta de arquitectura
            {proposal && <span className="ml-2 text-sm font-normal text-gray-500">· iteración {proposal.iteration}</span>}
          </h2>
          <p className="text-sm text-gray-500">Genera una propuesta basada en los requerimientos aprobados.</p>
        </div>
        {proposal && !streaming && <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${lifecycleStyle[proposal.lifecycle]}`}>{lifecycleLabel[proposal.lifecycle]}</span>}
        {approvedWithoutContent && <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${lifecycleStyle.approved}`}>{lifecycleLabel.approved}</span>}
      </div>

      {activity === 'loading' && <div className="mt-4 flex items-center gap-2 text-sm text-gray-500"><span className="h-4 w-4 animate-spin rounded-full border-2 border-sky-200 border-b-sky-600" /> Cargando propuesta...</div>}

      {approvedWithoutContent && (
        <p className="mt-4 rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
          La propuesta de este proyecto ya fue aprobada{projectState?.approved_at ? ` el ${formatDateTime(projectState.approved_at)}` : ''}. La fase está lista para avanzar.
        </p>
      )}

      {!proposal && !busy && !approvedWithoutContent && (
        <button type="button" onClick={() => generate(projectId)} data-testid="proposal-generate" className="mt-4 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 dark:hover:bg-solid-blue-700">
          {error ? 'Reintentar' : 'Generar propuesta'}
        </button>
      )}

      {proposal?.feedback && <p className="mt-3 rounded-lg bg-sky-50 px-3 py-2 text-xs text-sky-800">Ajuste solicitado: {proposal.feedback}</p>}

      {streaming && !proposal?.content && <div className="mt-4 flex items-center gap-2 text-sm text-sky-700"><span className="h-4 w-4 animate-spin rounded-full border-2 border-sky-200 border-b-sky-600" /> {activity === 'modifying' ? 'Generando nueva iteración...' : 'Generando propuesta...'}</div>}

      {proposal?.content && (
        <div className="mt-4 space-y-2 rounded-xl bg-slate-50 p-4 text-sm leading-relaxed text-gray-800" data-testid="proposal-content">
          {renderMarkdownBlocks(proposal.content)}
          {streaming && <span className="inline-block h-4 w-1.5 animate-pulse bg-sky-500 align-middle" aria-hidden />}
        </div>
      )}

      {proposal && (proposal.citations.length > 0 || !streaming) && <Citations citations={proposal.citations} />}

      {proposal?.id && proposal.lifecycle === 'proposed' && !streaming && (
        <div className="mt-4 border-t border-gray-100 pt-4">
          <div className="flex flex-wrap gap-2">
            <button type="button" disabled={busy} onClick={() => void handleDecision('approve')} data-testid="proposal-approve" className="rounded-lg bg-solid-emerald-700 px-3 py-2 text-sm font-medium text-white hover:bg-solid-emerald-800 disabled:opacity-50">Aprobar</button>
            <button
              type="button"
              disabled={busy || iterationLimitReached}
              onClick={() => setShowFeedback((open) => !open)}
              title={iterationLimitReached ? `Máximo de ${MAX_ITERATIONS} iteraciones alcanzado` : undefined}
              data-testid="proposal-modify"
              className="rounded-lg border border-sky-200 bg-sky-50 px-3 py-2 text-sm font-medium text-sky-700 hover:bg-sky-100 disabled:opacity-50"
            >
              Modificar
            </button>
            <button type="button" disabled={busy} onClick={() => void handleDecision('reject')} data-testid="proposal-reject" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm font-medium text-red-700 hover:bg-red-100 disabled:opacity-50">Rechazar</button>
            <input value={comment} disabled={busy} onChange={(event) => setComment(event.target.value)} maxLength={2000} className="min-w-40 flex-1 rounded-lg border border-gray-200 px-3 py-2 text-sm" placeholder="Comentario opcional" aria-label="Comentario opcional sobre la decisión" />
          </div>
          <p className="mt-2 text-xs text-gray-500">Aprobar deja la fase lista para avanzar. Rechazar devuelve el proyecto a requerimientos.</p>

          {showFeedback && (
            <div className="mt-3 space-y-2">
              <label className="block text-sm font-medium text-gray-700" htmlFor="proposal-feedback">¿Qué debería cambiar?</label>
              <textarea id="proposal-feedback" value={feedback} onChange={(event) => setFeedback(event.target.value)} rows={3} maxLength={2000} className="w-full rounded-lg border border-sky-200 p-3 text-sm outline-none focus:border-sky-500 focus:ring-2 focus:ring-sky-500/40" placeholder="Ej.: incluir caché, cambiar tecnología o ajustar una decisión..." />
              <div className="flex gap-2"><button type="button" onClick={submitModification} disabled={!feedback.trim() || busy} className="rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-700 dark:hover:bg-solid-blue-700 disabled:opacity-50">Generar nueva iteración</button><button type="button" onClick={() => setShowFeedback(false)} className="rounded-lg px-3 py-2 text-sm text-gray-600 hover:bg-gray-100">Cancelar</button></div>
            </div>
          )}
          {iterationLimitReached && <p className="mt-2 text-xs text-amber-700">Se alcanzó el máximo de {MAX_ITERATIONS} iteraciones: aprueba o rechaza la propuesta.</p>}
        </div>
      )}

      {iterations.length > 1 && <p className="mt-3 text-xs text-gray-500">{iterations.length} iteraciones generadas en esta sesión. Se muestra la más reciente.</p>}
      {error && <p className="mt-3 rounded-lg bg-red-50 p-3 text-sm text-red-700" role="alert">{error}</p>}
    </section>
  )
}

function Citations({ citations }: { citations: ProposalCitation[] }) {
  if (!citations.length) return <p className="mt-3 text-xs italic text-gray-500">Sin patrones recuperados de la base vectorial: propuesta basada en el conocimiento general del modelo.</p>
  return <div className="mt-3 border-t border-gray-100 pt-3 text-xs text-gray-600"><p className="font-semibold">Patrones citados (RAG)</p><ul className="mt-1 space-y-1">{citations.map((citation, index) => <li key={`${citation.pattern_id ?? 'pattern'}-${index}`} title={citation.snippet ?? undefined}>{citation.pattern_name ?? `Patrón #${citation.pattern_id ?? index + 1}`}{citation.similarity != null && ` · similitud ${(citation.similarity * 100).toFixed(0)}%`}</li>)}</ul></div>
}
