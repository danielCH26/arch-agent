import { useEffect, useState } from 'react'
import { proposalsStore } from '../stores/proposalsStore'
import type { ProposalCitation, ProposalJustification } from '../api/proposals'
import { getPatternDetail, type PatternDetail } from '../api/patterns'
import { renderMarkdownBlocks } from './MessageBubble'
import { ProposalProgress } from './ProposalProgress'
import { formatDateTime } from '../lib/format'

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
  const { current, iterations, projectState, activity, error, errorRetryable, cancelled, lastModify, load, generate, modify, retry, decide, reset } = proposalsStore()
  const [showFeedback, setShowFeedback] = useState(false)
  const [feedback, setFeedback] = useState('')
  const [comment, setComment] = useState('')
  const [confirmingReject, setConfirmingReject] = useState(false)

  useEffect(() => {
    // Si ya hay una propuesta de este proyecto en curso, no se recarga:
    // load() reinicia el estado y cortaría el stream.
    const { activity, current } = proposalsStore.getState()
    const streamingHere = (activity === 'generating' || activity === 'modifying') && current?.projectId === projectId
    if (!streamingHere) void load(projectId)
    return () => reset()
  }, [projectId, load, reset])

  const proposal = current?.projectId === projectId ? current : null
  const streaming = activity === 'generating' || activity === 'modifying'
  const busy = activity !== 'idle'
  const approvedWithoutContent = !proposal && projectState?.approved
  // El tope lo define el backend (PROPOSAL_MAX_ITER). Si no lo informa, no se
  // bloquea en el cliente: el servidor rechaza la iteración de más con su mensaje.
  const maxIterations = projectState?.max_iterations ?? null
  const iterationLimitReached = maxIterations !== null && (proposal?.iteration ?? 0) >= maxIterations
  // Si una modificación falla, se corta por el tope de tiempo o se cancela, el
  // feedback ya no está en el formulario: "Reintentar" lo reenvía.
  // Reintentar solo sirve para cortes transitorios. Un 4xx, el límite de
  // iteraciones o una configuración LLM inválida requieren una acción distinta.
  // Lo decide el backend con el campo estructurado `retryable` del evento SSE
  // `error`; el texto del mensaje es solo para mostrarlo y no se interpreta.
  const retryableError = error !== null && errorRetryable
  // Además, el feedback pendiente debe ser de ESTA propuesta: si la vigente ya
  // cambió (se rehidrató tras un corte al guardar), el `proposalId` viejo daría 409.
  const canRetry =
    lastModify !== null &&
    lastModify.proposalId === proposal?.id &&
    !busy &&
    (retryableError || cancelled)

  const handleDecision = async (decision: 'approve' | 'reject') => {
    if (!proposal?.id) return
    try {
      await decide(proposal.id, decision, comment.trim() || undefined, projectId)
      setComment('')
      setShowFeedback(false)
      setConfirmingReject(false)
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

      {/* F19: progreso visible + cancelar mientras se genera/modifica. */}
      <ProposalProgress />

      {cancelled && !error && !proposal && !busy && (
        <p className="mt-4 text-xs text-gray-500" role="status" data-testid="proposal-cancelled">
          Generación cancelada. Si ya se estaba guardando, la propuesta aparecerá aquí en unos segundos; si no, puedes volver a generarla.
        </p>
      )}

      {cancelled && !error && proposal?.id && !busy && (
        <p className="mt-3 text-xs text-gray-500" role="status" data-testid="proposal-modify-cancelled">
          Modificación cancelada. Se conserva la versión actual.
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

      {proposal && (proposal.citations.length > 0 || !streaming) && <Citations citations={proposal.citations} justification={streaming ? null : proposal.justification} />}

      {proposal?.id && proposal.lifecycle === 'proposed' && !streaming && (
        <div className="mt-4 border-t border-gray-100 pt-4">
          <div className="flex flex-wrap gap-2">
            <button type="button" disabled={busy} onClick={() => void handleDecision('approve')} data-testid="proposal-approve" className="rounded-lg bg-solid-emerald-700 px-3 py-2 text-sm font-medium text-white hover:bg-solid-emerald-800 disabled:opacity-50">Aprobar</button>
            <button
              type="button"
              disabled={busy || iterationLimitReached}
              onClick={() => { setConfirmingReject(false); setShowFeedback((open) => !open) }}
              title={iterationLimitReached ? `Máximo de ${maxIterations} iteraciones alcanzado` : undefined}
              data-testid="proposal-modify"
              className="rounded-lg border border-sky-200 bg-sky-50 px-3 py-2 text-sm font-medium text-sky-700 hover:bg-sky-100 disabled:opacity-50"
            >
              Modificar
            </button>
            <button type="button" disabled={busy || confirmingReject} onClick={() => { setShowFeedback(false); setConfirmingReject(true) }} data-testid="proposal-reject" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm font-medium text-red-700 hover:bg-red-100 disabled:opacity-50">Rechazar</button>
            <input value={comment} disabled={busy} onChange={(event) => setComment(event.target.value)} maxLength={2000} className="min-w-40 flex-1 rounded-lg border border-gray-200 px-3 py-2 text-sm" placeholder="Comentario opcional" aria-label="Comentario opcional sobre la decisión" />
          </div>
          <p className="mt-2 text-xs text-gray-500">Aprobar deja la fase lista para avanzar. Rechazar devuelve el proyecto a requerimientos.</p>

          {/* Rechazar revierte la fase y cierra las iteraciones: se confirma en línea, igual que en ApprovalPanel. */}
          {confirmingReject && (
            <div role="alertdialog" aria-labelledby="proposal-reject-confirm-text" className="mt-3 rounded-lg border border-red-200 bg-red-50 p-3" data-testid="proposal-reject-confirm">
              <p id="proposal-reject-confirm-text" className="text-sm text-red-700">
                ¿Seguro que quieres rechazar la propuesta? El proyecto vuelve a requerimientos y no se podrán generar más iteraciones de esta propuesta.
              </p>
              <div className="mt-3 flex flex-wrap gap-2">
                <button type="button" autoFocus disabled={busy} onClick={() => setConfirmingReject(false)} className="rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50">Cancelar</button>
                <button type="button" disabled={busy} onClick={() => void handleDecision('reject')} data-testid="proposal-reject-confirm-button" className="rounded-lg bg-red-600 px-3 py-2 text-sm font-medium text-white hover:bg-red-700 dark:hover:bg-solid-red-700 disabled:opacity-50">Sí, rechazar</button>
              </div>
            </div>
          )}

          {showFeedback && (
            <div className="mt-3 space-y-2">
              <label className="block text-sm font-medium text-gray-700" htmlFor="proposal-feedback">¿Qué debería cambiar?</label>
              <textarea id="proposal-feedback" value={feedback} onChange={(event) => setFeedback(event.target.value)} rows={3} maxLength={2000} className="w-full rounded-lg border border-sky-200 p-3 text-sm outline-none focus:border-sky-500 focus:ring-2 focus:ring-sky-500/40" placeholder="Ej.: incluir caché, cambiar tecnología o ajustar una decisión..." />
              <div className="flex gap-2"><button type="button" onClick={submitModification} disabled={!feedback.trim() || busy} className="rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-700 dark:hover:bg-solid-blue-700 disabled:cursor-not-allowed disabled:bg-gray-300">Generar nueva iteración</button><button type="button" onClick={() => setShowFeedback(false)} className="rounded-lg px-3 py-2 text-sm text-gray-600 hover:bg-gray-100">Cancelar</button></div>
            </div>
          )}
          {iterationLimitReached && <p className="mt-2 text-xs text-amber-700">Se alcanzó el máximo de {maxIterations} iteraciones: aprueba o rechaza la propuesta.</p>}
        </div>
      )}

      {iterations.length > 1 && <p className="mt-3 text-xs text-gray-500">{iterations.length} iteraciones generadas en esta sesión. Se muestra la más reciente.</p>}
      {error && <p className="mt-3 rounded-lg bg-red-50 p-3 text-sm text-red-700" role="alert">{error}</p>}
      {canRetry && (
        <div className="mt-2 flex flex-wrap items-center gap-2" data-testid="proposal-retry-panel">
          <button type="button" onClick={retry} className="rounded-lg border border-sky-200 bg-white px-3 py-1.5 text-xs font-semibold text-sky-700 hover:bg-sky-50" data-testid="proposal-retry">
            Reintentar con el mismo feedback
          </button>
          <span className="text-xs italic text-gray-500" data-testid="proposal-retry-feedback">“{lastModify?.feedback}”</span>
        </div>
      )}
    </section>
  )
}

function Citations({ citations, justification }: { citations: ProposalCitation[]; justification?: ProposalJustification | null }) {
  if (!citations.length) return <p className="mt-3 text-xs italic text-gray-500">Sin patrones recuperados de la base vectorial: propuesta basada en el conocimiento general del modelo.</p>
  return (
    <div className="mt-3 border-t border-gray-100 pt-3 text-xs text-gray-600">
      <p className="font-semibold">Fuentes RAG para los trade-offs:</p>
      {justification && <JustificationStatus justification={justification} />}
      {/* Sin numeración propia: el [n] ya es el número que cita la tabla. */}
      <ul className="mt-1 list-none space-y-1 pl-0">
        {citations.map((citation, index) => <CitationRow key={`${citation.pattern_id ?? 'pattern'}-${index}`} citation={citation} position={index + 1} />)}
      </ul>
    </div>
  )
}

// HU8: la propuesta cita patrones si declara el patrón principal recuperado y lo justifica.
function JustificationStatus({ justification }: { justification: ProposalJustification }) {
  if (justification.cites_patterns) {
    return <p className="mt-1 text-emerald-700" data-testid="justification-status">La propuesta justifica su patrón principal ({justification.primary_pattern_name}) con una fuente del catálogo.</p>
  }
  const reason = !justification.declared_primary
    ? 'no declara la línea “Patrón principal”'
    : !justification.primary_in_sources
      ? `su patrón principal (${justification.declared_primary}) no es la fuente principal recuperada`
      : 'falta la justificación del patrón principal'
  return <p className="mt-1 text-amber-700" data-testid="justification-status">La propuesta no cita patrones: {reason}.</p>
}

function CitationRow({ citation, position }: { citation: ProposalCitation; position: number }) {
  const [open, setOpen] = useState(false)
  const [detail, setDetail] = useState<PatternDetail | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const number = citation.index ?? position
  const patternId = citation.pattern_id

  const toggle = async () => {
    const next = !open
    setOpen(next)
    if (!next || detail || patternId == null) return
    try {
      setLoadError(null)
      setDetail(await getPatternDetail(patternId))
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : 'No se pudo cargar la fuente')
    }
  }

  return (
    <li title={citation.snippet ?? undefined} data-testid={`citation-${number}`}>
      [{number}] {citation.pattern_name ?? `Patrón #${patternId ?? number}`}
      {citation.similarity != null && ` · similitud ${(citation.similarity * 100).toFixed(0)}%`}
      {citation.source_role === 'primary' && <span className="ml-1 rounded bg-emerald-100 px-1 text-emerald-700">patrón principal</span>}
      {citation.source && <span className="block pl-6 text-gray-500">Fuente: {citation.source.label}</span>}
      {/* Fuentes curadas del patrón (libros, papers, docs oficiales): respaldo verificable de la cita. */}
      {(citation.fuentes?.length ?? 0) > 0 && (
        <ul className="ml-4 mt-0.5 list-disc space-y-0.5">
          {citation.fuentes!.map((source) => (
            <li key={`${source.titulo}-${source.url}`}>
              <a className="text-blue-700 underline hover:text-blue-900 dark:text-sky-300" href={source.url} target="_blank" rel="noopener noreferrer">
                {source.titulo}
              </a>
            </li>
          ))}
        </ul>
      )}
      {patternId != null && (
        <button type="button" onClick={() => void toggle()} aria-expanded={open} className="ml-6 text-blue-600 hover:underline">
          {open ? 'Ocultar fuente' : 'Verificar fuente'}
        </button>
      )}
      {open && (
        <div className="ml-6 mt-1 rounded bg-gray-50 p-2 text-gray-600">
          {citation.snippet && <blockquote className="border-l-2 border-gray-300 pl-2 italic">{citation.snippet}</blockquote>}
          {loadError && <p className="text-red-600">{loadError}</p>}
          {!detail && !loadError && <p className="italic">Cargando patrón...</p>}
          {detail && <PatternDetailView detail={detail} />}
        </div>
      )}
    </li>
  )
}

function PatternDetailView({ detail }: { detail: PatternDetail }) {
  const tradeoffs = (detail.tradeoffs ?? {}) as { ventajas?: string[]; desventajas?: string[] }
  const sources = Array.from(new Set(detail.chunks.map((chunk) => chunk.source)))
  return (
    <div className="mt-1 space-y-1" data-testid="pattern-detail">
      <p><span className="font-semibold">{detail.pattern_name}</span>{detail.category ? ` · ${detail.category}` : ''}</p>
      {detail.description && <p>{detail.description}</p>}
      {detail.use_cases && <p><span className="font-semibold">Cuándo usar:</span> {detail.use_cases}</p>}
      {detail.when_not_to_use && <p><span className="font-semibold">Cuándo no usar:</span> {detail.when_not_to_use}</p>}
      {tradeoffs.ventajas && tradeoffs.ventajas.length > 0 && <p><span className="font-semibold">Ventajas:</span> {tradeoffs.ventajas.join('; ')}</p>}
      {tradeoffs.desventajas && tradeoffs.desventajas.length > 0 && <p><span className="font-semibold">Desventajas:</span> {tradeoffs.desventajas.join('; ')}</p>}
      {sources.length > 0 && <p className="text-gray-500">Fuentes indexadas: {sources.join(', ')}</p>}
    </div>
  )
}
