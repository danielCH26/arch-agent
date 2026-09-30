import { useState } from 'react'
import {
  getPatternDetail,
  type PatternDetail,
  type ProposalCitation,
  type ProposalJustification,
} from '../../api/proposals'

interface CitationListProps {
  citations: ProposalCitation[]
  /** HU8: per-decision coverage; omitted while the stream is in flight. */
  justification?: ProposalJustification | null
}

/**
 * Renders the citations returned by the proposal generator.
 *
 * Each row shows:
 *   - the `[n]` number the proposal uses to reference it (HU8), anchored as
 *     `#proposal-cite-n` so inline references jump here
 *   - the pattern name (truncated if missing)
 *   - the similarity score as a percentage (matches the chat MessageBubble
 *     convention so users see one consistent metric across the app)
 *   - the source of the text (curated catalog or uploaded document) and
 *     whether the proposal actually cites it
 *   - a "Verificar fuente" toggle that loads the full pattern from
 *     `/api/patterns/{id}` so the user can check what backed the decision
 *   - a 240-char snippet tooltip via `title=` for hover-only inspection
 *
 * Empty list => "Sin contexto recuperado" placeholder (mirrors chat).
 */
export function CitationList({ citations, justification }: CitationListProps) {
  if (citations.length === 0) {
    return (
      <p className="text-xs italic text-gray-400">
        Sin contexto recuperado de la base vectorial — propuesta basada en
        conocimiento general del modelo.
      </p>
    )
  }

  return (
    <div className="mt-2 border-t border-gray-200 pt-2 text-xs text-gray-500">
      <span className="font-semibold">Patrones citados (PGVector):</span>
      {justification && justification.decisions_total > 0 && (
        <p
          className={`mt-1 ${
            justification.decisions_cited === justification.decisions_total
              ? 'text-green-700'
              : 'text-amber-700'
          }`}
          data-testid="justification-coverage"
        >
          {justification.decisions_cited} de {justification.decisions_total}{' '}
          decisiones justificadas con un patrón del catálogo
        </p>
      )}
      <ul className="mt-1 space-y-1">
        {citations.map((citation, index) => (
          <CitationRow
            key={`${citation.pattern_id ?? 'unknown'}-${index}`}
            citation={citation}
            position={index + 1}
          />
        ))}
      </ul>
    </div>
  )
}

function CitationRow({
  citation,
  position,
}: {
  citation: ProposalCitation
  position: number
}) {
  const [open, setOpen] = useState(false)
  const [detail, setDetail] = useState<PatternDetail | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)

  const number = citation.index ?? position
  const label = citation.pattern_name ?? `Patrón #${citation.pattern_id ?? position - 1}`
  const similarity =
    citation.similarity != null
      ? ` — similitud ${(citation.similarity * 100).toFixed(0)}%`
      : ''

  const toggle = async () => {
    const next = !open
    setOpen(next)
    if (!next || detail || citation.pattern_id == null) return
    try {
      setLoadError(null)
      setDetail(await getPatternDetail(citation.pattern_id))
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : 'No se pudo cargar la fuente')
    }
  }

  return (
    <li
      id={`proposal-cite-${number}`}
      title={citation.snippet ?? undefined}
      data-testid={`citation-${number}`}
    >
      <span className="font-mono">[{number}]</span> {label}
      {similarity}
      {citation.cited && (
        <span className="ml-1 rounded bg-green-100 px-1 text-green-700">
          citado en la propuesta
        </span>
      )}
      {citation.source && (
        <span className="block pl-6 text-gray-400">
          Fuente: {citation.source.label}
        </span>
      )}
      {citation.pattern_id != null && (
        <button
          type="button"
          onClick={() => void toggle()}
          className="ml-6 text-blue-600 hover:underline"
          aria-expanded={open}
        >
          {open ? 'Ocultar fuente' : 'Verificar fuente'}
        </button>
      )}
      {open && (
        <div className="ml-6 mt-1 rounded bg-gray-50 p-2 text-gray-600">
          {citation.snippet && (
            <blockquote className="border-l-2 border-gray-300 pl-2 italic">
              {citation.snippet}
            </blockquote>
          )}
          {loadError && <p className="text-red-600">{loadError}</p>}
          {!detail && !loadError && <p className="italic">Cargando patrón...</p>}
          {detail && <PatternDetailView detail={detail} />}
        </div>
      )}
    </li>
  )
}

function PatternDetailView({ detail }: { detail: PatternDetail }) {
  return (
    <div className="mt-1 space-y-1" data-testid="pattern-detail">
      <p>
        <span className="font-semibold">{detail.pattern_name}</span>
        {detail.category ? ` · ${detail.category}` : ''}
      </p>
      {detail.description && <p>{detail.description}</p>}
      {detail.use_cases && (
        <p>
          <span className="font-semibold">Cuándo usar:</span> {detail.use_cases}
        </p>
      )}
      {detail.when_not_to_use && (
        <p>
          <span className="font-semibold">Cuándo no usar:</span>{' '}
          {detail.when_not_to_use}
        </p>
      )}
      {detail.tradeoffs?.ventajas && detail.tradeoffs.ventajas.length > 0 && (
        <p>
          <span className="font-semibold">Ventajas:</span>{' '}
          {detail.tradeoffs.ventajas.join('; ')}
        </p>
      )}
      {detail.tradeoffs?.desventajas && detail.tradeoffs.desventajas.length > 0 && (
        <p>
          <span className="font-semibold">Desventajas:</span>{' '}
          {detail.tradeoffs.desventajas.join('; ')}
        </p>
      )}
      {detail.chunks.length > 0 && (
        <p className="text-gray-400">
          Fuentes indexadas:{' '}
          {Array.from(new Set(detail.chunks.map((c) => c.source))).join(', ')}
        </p>
      )}
    </div>
  )
}
