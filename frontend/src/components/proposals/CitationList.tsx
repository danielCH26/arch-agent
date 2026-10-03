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

  const primary = citations.find((citation) => citation.source_role === 'primary') ?? citations[0]
  const secondary = citations.filter((citation) => citation !== primary)
  const labelFor = (citation: ProposalCitation, index: number) =>
    citation.pattern_name ?? `Patrón #${citation.pattern_id ?? index}`

  return (
    <div className="mt-2 border-t border-gray-200 pt-2 text-xs text-gray-500">
      <p>
        <span className="font-semibold">Patrón principal:</span>{' '}
        <span title={primary.snippet ?? undefined}>{labelFor(primary, 0)}</span>
      </p>
      {secondary.length > 0 && (
        <p className="mt-1">
          <span className="font-semibold">Consultados no citados:</span>{' '}
          {secondary.map((citation, index) => (
            <span key={`${citation.pattern_id ?? 'unknown'}-${index}`} title={citation.snippet ?? undefined}>
              {index > 0 ? ', ' : ''}{labelFor(citation, index + 1)}
            </span>
          ))}
        </p>
      )}
    </div>
  )
}
