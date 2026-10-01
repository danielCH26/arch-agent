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

  const labelFor = (citation: ProposalCitation, index: number) =>
    citation.pattern_name ?? `Patrón #${citation.pattern_id ?? index}`

  return (
    <div className="mt-2 border-t border-gray-200 pt-2 text-xs text-gray-500">
      <p className="font-semibold">Fuentes RAG para los trade-offs:</p>
      <ol className="mt-1 list-decimal pl-4">
        {citations.map((citation, index) => (
          <li key={`${citation.pattern_id ?? 'unknown'}-${index}`}>
            <span title={citation.snippet ?? undefined}>[{index + 1}] {labelFor(citation, index)}</span>
          </li>
        ))}
      </ol>
    </div>
  )
}
