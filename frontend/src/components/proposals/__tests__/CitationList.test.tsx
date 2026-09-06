import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { CitationList } from '../CitationList'
import type { ProposalCitation } from '../../../api/proposals'

describe('CitationList', () => {
  it('renders a row per citation with similarity as percentage', () => {
    const citations: ProposalCitation[] = [
      { pattern_id: 7, pattern_name: 'Hexagonal', similarity: 0.91 },
      { pattern_id: 11, pattern_name: 'BFF', similarity: 0.88 },
    ]

    render(<CitationList citations={citations} />)

    expect(screen.getByText(/Hexagonal/)).toBeInTheDocument()
    expect(screen.getByText(/similitud 91%/)).toBeInTheDocument()
    expect(screen.getByText(/BFF/)).toBeInTheDocument()
    expect(screen.getByText(/similitud 88%/)).toBeInTheDocument()
  })

  it('omits the similarity percentage when similarity is missing', () => {
    const citations: ProposalCitation[] = [
      { pattern_id: 3, pattern_name: 'Event Sourcing', similarity: null },
    ]

    render(<CitationList citations={citations} />)

    const row = screen.getByText(/Event Sourcing/)
    expect(row.textContent).not.toContain('similitud')
  })

  it('shows the empty-state message when no citations pass the threshold', () => {
    render(<CitationList citations={[]} />)

    expect(
      screen.getByText(/Sin contexto recuperado de la base vectorial/),
    ).toBeInTheDocument()
  })

  it('falls back to a generic label when pattern_name is missing', () => {
    const citations: ProposalCitation[] = [
      { pattern_id: 42, pattern_name: null, similarity: 0.9 },
    ]

    render(<CitationList citations={citations} />)

    // Falls back to "Patrón #<id>" so reviewers can still see the reference.
    expect(screen.getByText(/Patrón #42/)).toBeInTheDocument()
  })

  it('uses snippet as a tooltip for additional context', () => {
    const citations: ProposalCitation[] = [
      {
        pattern_id: 1,
        pattern_name: 'Saga',
        similarity: 0.92,
        snippet: 'Orquesta transacciones distribuidas',
      },
    ]

    render(<CitationList citations={citations} />)

    const li = screen.getByText(/Saga/).closest('li')
    expect(li?.getAttribute('title')).toBe(
      'Orquesta transacciones distribuidas',
    )
  })
})