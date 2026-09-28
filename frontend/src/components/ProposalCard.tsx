import { useEffect, useState } from 'react'
import { proposalsStore } from '../stores/proposalsStore'
import type { ProposalCitation } from '../api/proposals'

interface ProposalCardProps {
  projectId: number
  onPhaseChanged?: () => void | Promise<void>
}

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
  const { current, iterations, activity, error, generate, modify, decide, reset } = proposalsStore()
  const [showFeedback, setShowFeedback] = useState(false)
  const [feedback, setFeedback] = useState('')
  const [comment, setComment] = useState('')

  useEffect(() => {
    reset()
  }, [projectId, reset])

  const proposal = current?.projectId === projectId ? current : null
  const busy = activity !== 'idle'

  const handleDecision = async (decision: 'approve' | 'reject') => {
    if (!proposal?.id) return
    await decide(proposal.id, decision, comment.trim() || undefined)
    setComment('')
    await onPhaseChanged?.()
  }

  const submitModification = () => {
    if (!proposal?.id || !feedback.trim()) return
    modify(proposal.id, feedback.trim())
    setFeedback('')
    setShowFeedback(false)
  }

  return (
    <section className="mb-4 rounded-2xl border border-sky-200 bg-white p-4 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-base font-semibold text-gray-900">Propuesta de arquitectura</h2>
          <p className="text-sm text-gray-500">Genera una propuesta basada en los requerimientos aprobados.</p>
        </div>
        {proposal && <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${lifecycleStyle[proposal.lifecycle]}`}>{lifecycleLabel[proposal.lifecycle]}</span>}
      </div>

      {!proposal && !busy && (
        <button type="button" onClick={() => generate(projectId)} className="mt-4 rounded-lg bg-sky-600 px-4 py-2 text-sm font-medium text-white hover:bg-sky-700">
          Generar propuesta
        </button>
      )}

      {busy && !proposal?.content && <div className="mt-4 flex items-center gap-2 text-sm text-sky-700"><span className="h-4 w-4 animate-spin rounded-full border-2 border-sky-200 border-b-sky-600" /> Generando propuesta...</div>}

      {proposal?.content && <div className="mt-4 whitespace-pre-wrap rounded-xl bg-slate-50 p-4 text-sm leading-relaxed text-gray-800">{proposal.content}</div>}

      {proposal?.feedback && <p className="mt-3 rounded-lg bg-sky-50 px-3 py-2 text-xs text-sky-800">Ajuste solicitado: {proposal.feedback}</p>}

      {proposal && <Citations citations={proposal.citations} />}

      {proposal?.id && proposal.lifecycle === 'proposed' && !busy && (
        <div className="mt-4 border-t border-gray-100 pt-4">
          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={() => void handleDecision('approve')} className="rounded-lg bg-emerald-600 px-3 py-2 text-sm font-medium text-white hover:bg-emerald-700">Aprobar</button>
            <button type="button" onClick={() => setShowFeedback((open) => !open)} className="rounded-lg border border-sky-200 bg-sky-50 px-3 py-2 text-sm font-medium text-sky-700 hover:bg-sky-100">Modificar</button>
            <button type="button" onClick={() => void handleDecision('reject')} className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm font-medium text-red-700 hover:bg-red-100">Rechazar</button>
            <input value={comment} onChange={(event) => setComment(event.target.value)} className="min-w-40 flex-1 rounded-lg border border-gray-200 px-3 py-2 text-sm" placeholder="Comentario opcional" />
          </div>

          {showFeedback && (
            <div className="mt-3 space-y-2">
              <label className="block text-sm font-medium text-gray-700" htmlFor="proposal-feedback">¿Qué debería cambiar?</label>
              <textarea id="proposal-feedback" value={feedback} onChange={(event) => setFeedback(event.target.value)} rows={3} className="w-full rounded-lg border border-sky-200 p-3 text-sm outline-none focus:border-sky-500" placeholder="Ej.: incluir caché, cambiar tecnología o ajustar una decisión..." />
              <div className="flex gap-2"><button type="button" onClick={submitModification} disabled={!feedback.trim()} className="rounded-lg bg-sky-600 px-3 py-2 text-sm font-medium text-white hover:bg-sky-700 disabled:opacity-50">Generar nueva iteración</button><button type="button" onClick={() => setShowFeedback(false)} className="rounded-lg px-3 py-2 text-sm text-gray-600 hover:bg-gray-100">Cancelar</button></div>
            </div>
          )}
        </div>
      )}

      {iterations.length > 1 && <p className="mt-3 text-xs text-gray-500">{iterations.length} iteraciones generadas. Se muestra la más reciente.</p>}
      {error && <p className="mt-3 rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</p>}
    </section>
  )
}

function Citations({ citations }: { citations: ProposalCitation[] }) {
  if (!citations.length) return <p className="mt-3 text-xs italic text-gray-400">Sin patrones recuperados de la base vectorial.</p>
  return <div className="mt-3 border-t border-gray-100 pt-3 text-xs text-gray-600"><p className="font-semibold">Patrones citados</p><ul className="mt-1 space-y-1">{citations.map((citation, index) => <li key={`${citation.pattern_id ?? 'pattern'}-${index}`} title={citation.snippet ?? undefined}>{citation.pattern_name ?? `Patrón #${citation.pattern_id ?? index + 1}`}{citation.similarity != null && ` · similitud ${(citation.similarity * 100).toFixed(0)}%`}</li>)}</ul></div>
}
