import type { ProposalCitation } from '../../api/proposals'

interface CitationListProps {
  citations: ProposalCitation[]
}

/**
 * Renders the citations returned by the proposal generator.
 *
 * Each row shows:
 *   - the pattern name (truncated if missing)
 *   - the similarity score as a percentage (matches the chat MessageBubble
 *     convention so users see one consistent metric across the app)
 *   - a 240-char snippet tooltip via `title=` for hover-only inspection
 *
 * Empty list => "Sin contexto recuperado" placeholder (mirrors chat).
 */
export function CitationList({ citations }: CitationListProps) {
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
      <ul className="mt-1 space-y-1">
        {citations.map((citation, index) => {
          const label =
            citation.pattern_name ?? `Patrón #${citation.pattern_id ?? index}`
          const similarity =
            citation.similarity != null
              ? ` — similitud ${(citation.similarity * 100).toFixed(0)}%`
              : ''
          return (
            <li
              key={`${citation.pattern_id ?? 'unknown'}-${index}`}
              title={citation.snippet ?? undefined}
            >
              {label}
              {similarity}
            </li>
          )
        })}
      </ul>
    </div>
  )
}