import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../../api/adr', () => ({ getAdr: vi.fn(), generateAdr: vi.fn() }))
vi.mock('../../api/diagrams', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/diagrams')>()
  return { ...actual, fetchDiagramHistory: vi.fn() }
})

import { AdrPanel, adrFilename } from '../AdrPanel'
import { generateAdr, getAdr } from '../../api/adr'
import { fetchDiagramHistory } from '../../api/diagrams'

const ADR = {
  markdown: '# ADR-001: Arquitectura de Clínica\n\n## 1. Contexto\n\nCitas por teléfono',
  generated_at: '2026-10-16T15:00:00+00:00',
  guide_complete: true,
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(fetchDiagramHistory).mockResolvedValue([])
})

describe('AdrPanel', () => {
  it('sin ADR guardado ofrece generarlo', async () => {
    vi.mocked(getAdr).mockResolvedValue({ markdown: null, generated_at: null, guide_complete: false })

    render(<AdrPanel projectId={5} projectName="Clínica" />)

    expect(await screen.findByTestId('adr-empty')).toBeInTheDocument()
    expect(screen.getByTestId('adr-generate')).toHaveTextContent('Generar ADR')
    expect(screen.queryByTestId('adr-download')).not.toBeInTheDocument()
  })

  it('muestra el ADR guardado con descarga y opción de regenerar', async () => {
    vi.mocked(getAdr).mockResolvedValue(ADR)

    render(<AdrPanel projectId={5} projectName="Clínica" />)

    expect(await screen.findByTestId('adr-content')).toHaveTextContent('Citas por teléfono')
    expect(screen.getByTestId('adr-download')).toBeInTheDocument()
    expect(screen.getByTestId('adr-generate')).toHaveTextContent('Regenerar ADR')
    expect(screen.queryByTestId('adr-guide-incomplete')).not.toBeInTheDocument()
  })

  it('genera el ADR al pulsar el botón', async () => {
    vi.mocked(getAdr).mockResolvedValue({ markdown: null, generated_at: null, guide_complete: false })
    vi.mocked(generateAdr).mockResolvedValue({ ...ADR, guide_complete: false })

    render(<AdrPanel projectId={5} />)
    await userEvent.click(await screen.findByTestId('adr-generate'))

    expect(generateAdr).toHaveBeenCalledWith(5)
    expect(await screen.findByTestId('adr-content')).toBeInTheDocument()
    // Sin guía del LLM se avisa, pero el documento se muestra igual.
    expect(screen.getByTestId('adr-guide-incomplete')).toBeInTheDocument()
  })

  it('muestra el error del backend (p. ej. sin propuesta aprobada)', async () => {
    vi.mocked(getAdr).mockResolvedValue({ markdown: null, generated_at: null, guide_complete: false })
    vi.mocked(generateAdr).mockRejectedValue(new Error('Todavía no hay una propuesta aprobada.'))

    render(<AdrPanel projectId={5} />)
    await userEvent.click(await screen.findByTestId('adr-generate'))

    expect(await screen.findByTestId('adr-error')).toHaveTextContent('propuesta aprobada')
  })

  it('muestra la imagen del diagrama aprobado junto al ADR', async () => {
    vi.mocked(getAdr).mockResolvedValue(ADR)
    vi.mocked(fetchDiagramHistory).mockResolvedValue([
      { message_id: 2, id: 'b', url: '/ultimo.png', filename: null, created_at: '', decision: null },
      { message_id: 1, id: 'a', url: '/aprobado.png', filename: null, created_at: '', decision: 'approve' },
    ])

    render(<AdrPanel projectId={5} />)

    await waitFor(() => expect(screen.getByTestId('adr-diagram')).toBeInTheDocument())
    expect(screen.getByRole('img')).toHaveAttribute('src', '/aprobado.png')
    expect(screen.getByText('Diagrama aprobado')).toBeInTheDocument()
  })

  it('arma un nombre de archivo seguro', () => {
    expect(adrFilename('Clínica Médica 2.0')).toBe('ADR-clinica-medica-2-0.md')
    expect(adrFilename(null)).toBe('ADR-proyecto.md')
  })
})
