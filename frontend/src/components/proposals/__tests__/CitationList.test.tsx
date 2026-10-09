import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { CitationList } from '../CitationList'
import * as proposalsApi from '../../../api/proposals'
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

  describe('HU8 — fuentes verificables', () => {
    afterEach(() => vi.restoreAllMocks())

    const hu8Citation: ProposalCitation = {
      index: 2,
      pattern_id: 7,
      pattern_name: 'Hexagonal',
      similarity: 0.93,
      snippet: 'Puertos y adaptadores',
      source: {
        type: 'curated_catalog',
        label: 'Catálogo curado de patrones (arch-agent)',
        filename: null,
      },
      verify_url: '/api/patterns/7',
      cited: true,
    }

    it('shows the [n] number, source and cited badge anchored for inline refs', () => {
      render(<CitationList citations={[hu8Citation]} />)

      const row = screen.getByTestId('citation-2')
      expect(row.id).toBe('proposal-cite-2')
      expect(row.textContent).toContain('[2]')
      expect(
        screen.getByText(/Fuente: Catálogo curado de patrones/),
      ).toBeInTheDocument()
      expect(screen.getByText('citado en la propuesta')).toBeInTheDocument()
    })

    it('shows how many decisions are justified', () => {
      render(
        <CitationList
          citations={[hu8Citation]}
          justification={{
            decisions_total: 5,
            decisions_cited: 4,
            coverage: 0.8,
            cites_patterns: true,
            cited_indices: [2],
            invalid_refs: [],
            uncited_decisions: [],
          }}
        />,
      )

      expect(screen.getByTestId('justification-coverage').textContent).toMatch(
        /4 de 5 decisiones justificadas/,
      )
    })

    it('loads the full pattern when the user verifies the source', async () => {
      const spy = vi.spyOn(proposalsApi, 'getPatternDetail').mockResolvedValue({
        id: 7,
        pattern_name: 'Hexagonal',
        category: 'Estructural',
        description: 'Aísla el dominio de la infraestructura',
        use_cases: 'Dominios ricos',
        tradeoffs: { ventajas: ['Testeable'], desventajas: ['Más capas'] },
        when_not_to_use: 'CRUD simple',
        decision_signals: [],
        chunks: [
          {
            id: 1,
            chunk_type: 'summary',
            chunk_text: 'x',
            source: 'Catálogo curado de patrones (arch-agent)',
          },
        ],
      })

      render(<CitationList citations={[hu8Citation]} />)
      fireEvent.click(screen.getByRole('button', { name: 'Verificar fuente' }))

      await waitFor(() =>
        expect(screen.getByTestId('pattern-detail')).toBeInTheDocument(),
      )
      expect(spy).toHaveBeenCalledWith(7)
      expect(
        screen.getByText(/Aísla el dominio de la infraestructura/),
      ).toBeInTheDocument()
      expect(screen.getByText(/Más capas/)).toBeInTheDocument()
    })
  })
})
