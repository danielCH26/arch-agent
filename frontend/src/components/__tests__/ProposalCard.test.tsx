import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ProposalCard } from '../ProposalCard'
import { getPatternDetail } from '../../api/patterns'
import { proposalsStore } from '../../stores/proposalsStore'
import {
  createProposalStream,
  decideProposal,
  getProjectProposalState,
  getProposal,
  type ProjectProposalState,
  type ProposalOut,
} from '../../api/proposals'

vi.mock('../../api/proposals', () => ({
  createProposalStream: vi.fn(),
  decideProposal: vi.fn(),
  getLatestProposal: vi.fn(),
  getProjectProposalState: vi.fn(),
  getProposal: vi.fn(),
}))

vi.mock('../../api/patterns', () => ({
  getPatternDetail: vi.fn(),
}))

type Callbacks = Parameters<typeof createProposalStream>[2]

const PROJECT_ID = 7

const state = (overrides: Partial<ProjectProposalState> = {}): ProjectProposalState => ({
  approved: false,
  approved_at: null,
  approval_id: null,
  proposal_snapshot_chars: 0,
  last_decision: null,
  ...overrides,
})

const proposalOut = (overrides: Partial<ProposalOut> = {}): ProposalOut => ({
  id: 41,
  project_id: PROJECT_ID,
  iteration: 1,
  content: 'Arquitectura en capas',
  citations: [],
  feedback: null,
  lifecycle: 'proposed',
  created_at: '2026-10-01T10:00:00Z',
  ...overrides,
})

let streams: Callbacks[] = []

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  streams = []
  proposalsStore.getState().reset()
  vi.mocked(createProposalStream).mockImplementation((_mode, _payload, callbacks) => {
    streams.push(callbacks)
    return () => undefined
  })
  vi.mocked(getProjectProposalState).mockResolvedValue(state())
})

afterEach(() => {
  proposalsStore.getState().reset()
})

async function renderWithProposal(proposal: ProposalOut, projectState = state()) {
  vi.mocked(getProjectProposalState).mockResolvedValue(projectState)
  vi.mocked(getProposal).mockResolvedValue(proposal)
  // La tarjeta rehidrata la última propuesta recordada en el navegador.
  localStorage.setItem(`archagent:user:anon:last-proposal:${PROJECT_ID}`, String(proposal.id))
  render(<ProposalCard projectId={PROJECT_ID} />)
  await screen.findByTestId('proposal-content')
}

describe('ProposalCard', () => {
  it('pide confirmación antes de rechazar y no decide si se cancela', async () => {
    const user = userEvent.setup()
    await renderWithProposal(proposalOut())

    await user.click(screen.getByTestId('proposal-reject'))
    expect(screen.getByRole('alertdialog')).toBeInTheDocument()
    expect(decideProposal).not.toHaveBeenCalled()

    await user.click(screen.getByRole('button', { name: 'Cancelar' }))
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
    expect(decideProposal).not.toHaveBeenCalled()
  })

  it('rechaza solo tras confirmar', async () => {
    const user = userEvent.setup()
    vi.mocked(decideProposal).mockResolvedValue({ proposal_id: 41, lifecycle: 'rejected', current_phase: 'requerimientos', phase_ready: false })
    await renderWithProposal(proposalOut())

    await user.click(screen.getByTestId('proposal-reject'))
    await user.click(screen.getByTestId('proposal-reject-confirm-button'))

    // Se manda el proyecto abierto: el backend responde 409 si la propuesta es de otro.
    expect(decideProposal).toHaveBeenCalledWith(41, 'reject', undefined, PROJECT_ID)
  })

  it('usa el tope de iteraciones que informa el backend', async () => {
    await renderWithProposal(proposalOut({ iteration: 3 }), state({ max_iterations: 3 }))

    expect(screen.getByTestId('proposal-modify')).toBeDisabled()
    expect(screen.getByText(/máximo de 3 iteraciones/)).toBeInTheDocument()
  })

  it('no bloquea "Modificar" por su cuenta si el backend no informa el tope', async () => {
    await renderWithProposal(proposalOut({ iteration: 5 }))

    expect(screen.getByTestId('proposal-modify')).toBeEnabled()
  })

  it('recupera la propuesta generada mientras el usuario estaba en otra página', async () => {
    const user = userEvent.setup()
    vi.mocked(getProposal).mockResolvedValue(proposalOut())
    const first = render(<ProposalCard projectId={PROJECT_ID} />)
    await user.click(await screen.findByTestId('proposal-generate'))
    expect(streams).toHaveLength(1)

    // Sale de la página con la generación en curso y vuelve antes de que termine.
    first.unmount()
    render(<ProposalCard projectId={PROJECT_ID} />)
    expect(await screen.findByText('Generando propuesta...')).toBeInTheDocument()
    expect(screen.queryByTestId('proposal-generate')).not.toBeInTheDocument()

    act(() => streams[0].onDone(41, []))

    expect(await screen.findByTestId('proposal-content')).toHaveTextContent('Arquitectura en capas')
    expect(getProposal).toHaveBeenCalledWith(41)
    // Solo se generó una vez: no se gastó otra iteración.
    expect(createProposalStream).toHaveBeenCalledTimes(1)
  })

  it('recuerda la propuesta aunque termine sin la tarjeta montada', async () => {
    const user = userEvent.setup()
    const first = render(<ProposalCard projectId={PROJECT_ID} />)
    await user.click(await screen.findByTestId('proposal-generate'))
    first.unmount()

    act(() => streams[0].onDone(41, []))

    vi.mocked(getProposal).mockResolvedValue(proposalOut())
    render(<ProposalCard projectId={PROJECT_ID} />)
    await waitFor(() => expect(screen.getByTestId('proposal-content')).toHaveTextContent('Arquitectura en capas'))
  })

  describe('fallo a mitad de stream (sin dead-end)', () => {
    it('al fallar generar tras recibir tokens muestra el error y ofrece reintentar', async () => {
      const user = userEvent.setup()
      render(<ProposalCard projectId={PROJECT_ID} />)
      await user.click(await screen.findByTestId('proposal-generate'))

      act(() => streams[0].onToken('## Contexto parcial'))
      expect(await screen.findByTestId('proposal-content')).toHaveTextContent('Contexto parcial')

      // El backend no persiste la propuesta truncada y emite `error` después de los tokens.
      act(() => streams[0].onError('La generación terminó antes de completarse.'))

      expect(await screen.findByRole('alert')).toHaveTextContent('La generación terminó antes de completarse.')
      expect(screen.queryByTestId('proposal-content')).not.toBeInTheDocument()
      // Sin id no hay acciones de decisión sobre una propuesta que no existe.
      expect(screen.queryByTestId('proposal-approve')).not.toBeInTheDocument()
      const retry = screen.getByTestId('proposal-generate')
      expect(retry).toHaveTextContent('Reintentar')

      await user.click(retry)
      expect(createProposalStream).toHaveBeenCalledTimes(2)
      expect(screen.queryByRole('alert')).not.toBeInTheDocument()

      // Cierra el stream del reintento: el store rastrea streams por proyecto a
      // nivel de módulo y uno abierto bloquearía el load() de los demás tests.
      act(() => streams[1].onError('Reintento cancelado en el test.'))
    })

    it('al fallar modificar tras recibir tokens vuelve a la propuesta anterior con su error', async () => {
      const user = userEvent.setup()
      await renderWithProposal(proposalOut())

      await user.click(screen.getByTestId('proposal-modify'))
      await user.type(screen.getByLabelText('¿Qué debería cambiar?'), 'incluir caché')
      await user.click(screen.getByRole('button', { name: 'Generar nueva iteración' }))
      expect(createProposalStream).toHaveBeenCalledWith('modify', expect.objectContaining({ proposalId: 41 }), expect.anything())

      act(() => streams[0].onToken('Iteración parcial'))
      expect(await screen.findByTestId('proposal-content')).toHaveTextContent('Iteración parcial')

      act(() => streams[0].onError('La generación terminó antes de completarse.'))

      expect(await screen.findByRole('alert')).toHaveTextContent('La generación terminó antes de completarse.')
      expect(screen.getByTestId('proposal-content')).toHaveTextContent('Arquitectura en capas')
      expect(screen.getByTestId('proposal-content')).not.toHaveTextContent('Iteración parcial')
      // La iteración 1 sigue siendo accionable: se puede aprobar, modificar o rechazar.
      expect(screen.getByTestId('proposal-approve')).toBeEnabled()
      expect(screen.getByTestId('proposal-modify')).toBeEnabled()
    })

    it('un error de red al iniciar la generación también deja el botón de reintento', async () => {
      const user = userEvent.setup()
      render(<ProposalCard projectId={PROJECT_ID} />)
      await user.click(await screen.findByTestId('proposal-generate'))

      act(() => streams[0].onError('No se pudo conectar con el servidor.'))

      expect(await screen.findByRole('alert')).toHaveTextContent('No se pudo conectar con el servidor.')
      expect(screen.getByTestId('proposal-generate')).toHaveTextContent('Reintentar')
    })
  })

  describe('progreso, cancelar y reintentar (F19)', () => {
    it('muestra el progreso mientras genera y "Cancelar" vuelve a ofrecer generar', async () => {
      const user = userEvent.setup()
      render(<ProposalCard projectId={PROJECT_ID} />)
      await user.click(await screen.findByTestId('proposal-generate'))

      expect(screen.getByTestId('proposal-progress')).toBeInTheDocument()
      await user.click(screen.getByTestId('proposal-cancel-generation'))

      expect(screen.queryByTestId('proposal-progress')).not.toBeInTheDocument()
      expect(screen.getByTestId('proposal-cancelled')).toBeInTheDocument()
      expect(screen.getByTestId('proposal-generate')).toHaveTextContent('Generar propuesta')
    })

    it('tras un fallo de la modificación ofrece reintentar con el mismo feedback', async () => {
      const user = userEvent.setup()
      await renderWithProposal(proposalOut())

      await user.click(screen.getByTestId('proposal-modify'))
      await user.type(screen.getByLabelText('¿Qué debería cambiar?'), 'agrega caché')
      await user.click(screen.getByRole('button', { name: 'Generar nueva iteración' }))
      act(() => streams[0].onError('La generación superó el tiempo máximo (5 min)', undefined, { code: 'timeout', retryable: true }))

      expect(await screen.findByTestId('proposal-retry-feedback')).toHaveTextContent('agrega caché')
      await user.click(screen.getByTestId('proposal-retry'))

      expect(createProposalStream).toHaveBeenCalledTimes(2)
      expect(vi.mocked(createProposalStream).mock.calls[1][1]).toMatchObject({ proposalId: 41, feedback: 'agrega caché' })
      expect(screen.queryByTestId('proposal-retry')).not.toBeInTheDocument()
      act(() => streams[1].onError('Reintento cancelado en el test.'))
    })

    it('no ofrece reintentar ante un error permanente (p. ej. límite de iteraciones)', async () => {
      const user = userEvent.setup()
      await renderWithProposal(proposalOut())

      await user.click(screen.getByTestId('proposal-modify'))
      await user.type(screen.getByLabelText('¿Qué debería cambiar?'), 'x')
      await user.click(screen.getByRole('button', { name: 'Generar nueva iteración' }))
      act(() => streams[0].onError('Has alcanzado el máximo de iteraciones (5)', undefined, { code: 'rejected', retryable: false }))

      expect(await screen.findByRole('alert')).toHaveTextContent('máximo de iteraciones')
      expect(screen.queryByTestId('proposal-retry')).not.toBeInTheDocument()
    })

    it('no ofrece reintentar si el feedback pendiente es de otra propuesta (id viejo)', async () => {
      await renderWithProposal(proposalOut())
      act(() => proposalsStore.setState({
        error: 'La generación superó el tiempo máximo (5 min)',
        errorRetryable: true,
        lastModify: { proposalId: 40, feedback: 'agrega caché' },
      }))

      expect(screen.queryByTestId('proposal-retry')).not.toBeInTheDocument()
    })

    it('el reintento lo decide `retryable`, no la redacción del mensaje', async () => {
      const user = userEvent.setup()
      await renderWithProposal(proposalOut())

      await user.click(screen.getByTestId('proposal-modify'))
      await user.type(screen.getByLabelText('¿Qué debería cambiar?'), 'agrega caché')
      await user.click(screen.getByRole('button', { name: 'Generar nueva iteración' }))
      // El texto suena a timeout, pero el backend lo marca como permanente.
      act(() => streams[0].onError('La generación superó el tiempo máximo (5 min)', undefined, { code: 'rejected', retryable: false }))

      expect(await screen.findByRole('alert')).toHaveTextContent('tiempo máximo')
      expect(screen.queryByTestId('proposal-retry')).not.toBeInTheDocument()
    })

    it('un flag reintentable huérfano (sin error) no muestra el reintento', async () => {
      await renderWithProposal(proposalOut())
      act(() => proposalsStore.setState({ error: null, errorRetryable: true, lastModify: { proposalId: 41, feedback: 'x' } }))

      expect(screen.queryByTestId('proposal-retry')).not.toBeInTheDocument()
    })

    it('tras cancelar una modificación conserva la versión actual y permite reintentar', async () => {
      const user = userEvent.setup()
      await renderWithProposal(proposalOut())

      await user.click(screen.getByTestId('proposal-modify'))
      await user.type(screen.getByLabelText('¿Qué debería cambiar?'), 'agrega caché')
      await user.click(screen.getByRole('button', { name: 'Generar nueva iteración' }))
      await user.click(screen.getByTestId('proposal-cancel-generation'))

      expect(screen.getByTestId('proposal-content')).toHaveTextContent('Arquitectura en capas')
      expect(screen.getByTestId('proposal-modify-cancelled')).toBeInTheDocument()
      expect(screen.getByTestId('proposal-retry')).toBeInTheDocument()
    })
  })

  it('numera las fuentes RAG como [n] para que coincidan con las citas de la tabla', async () => {
    await renderWithProposal(proposalOut({
      citations: [
        { pattern_id: 7, pattern_name: 'Hexagonal', similarity: 0.91, source_role: 'primary' },
        { pattern_id: 11, pattern_name: 'BFF', similarity: 0.88, source_role: 'tradeoff_option' },
      ],
    }))

    expect(screen.getByText('Fuentes RAG para los trade-offs:')).toBeInTheDocument()
    expect(screen.getByText(/\[1\] Hexagonal/)).toBeInTheDocument()
    expect(screen.getByText(/\[2\] BFF/)).toBeInTheDocument()
    // Sin numeración propia de lista: el [n] ya es el número que cita la tabla.
    expect(document.querySelector('ol')).toBeNull()
  })

  it('muestra las fuentes curadas del patrón como links externos seguros', async () => {
    await renderWithProposal(proposalOut({
      citations: [{
        pattern_id: 7,
        pattern_name: 'Hexagonal',
        similarity: 0.91,
        fuentes: [{
          titulo: 'Hexagonal architecture (Alistair Cockburn)',
          url: 'https://alistair.cockburn.us/hexagonal-architecture/',
        }],
      }],
    }))

    const link = screen.getByRole('link', { name: /Alistair Cockburn/ })
    expect(link).toHaveAttribute('href', 'https://alistair.cockburn.us/hexagonal-architecture/')
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', 'noopener noreferrer')
  })

  it('renderiza la tabla de trade-offs con <br> en las celdas sin partir las filas', async () => {
    await renderWithProposal(proposalOut({
      content:
        '## Trade-offs y decisión\n| Opción | Ventajas | Desventajas | Complejidad/costo |\n| --- | --- | --- | --- |\n| Hexagonal | 1. Testeable.<br>2. Cambio de proveedor. | 1. Más código.<br />2. Curva de aprendizaje. | Media |\n| Modular | a | b | Baja |\n| Capas | a | b | Baja |',
    }))

    const table = screen.getByTestId('proposal-content').querySelector('table') as HTMLTableElement
    expect(table.textContent).not.toMatch(/<br/i)
    expect(table.querySelectorAll('br')).toHaveLength(2)
    expect(table.querySelectorAll('tbody tr')).toHaveLength(3)
  })
})

describe('ProposalCard HU8: justificación con patrones', () => {
  const citations = [
    {
      index: 1,
      pattern_id: 3,
      pattern_name: 'Monolito modular',
      similarity: 0.88,
      source_role: 'primary' as const,
      snippet: 'Un despliegue, módulos aislados',
      source: { type: 'curated_catalog' as const, label: 'Catálogo curado de patrones (arch-agent)', filename: null },
    },
    { index: 2, pattern_id: 8, pattern_name: 'Microservicios', similarity: 0.85, source_role: 'tradeoff_option' as const },
  ]
  const justification = {
    cites_patterns: true,
    declared_primary: 'monolito modular',
    primary_pattern_id: 3,
    primary_pattern_name: 'Monolito modular',
    primary_in_sources: true,
    justified: true,
  }

  it('marca el patrón principal, muestra la fuente y si la propuesta lo cita', async () => {
    await renderWithProposal(proposalOut({ citations, justification }))

    expect(screen.getByTestId('justification-status')).toHaveTextContent('justifica su patrón principal (Monolito modular)')
    expect(screen.getByTestId('citation-1')).toHaveTextContent('patrón principal')
    expect(screen.getByTestId('citation-1')).toHaveTextContent('Fuente: Catálogo curado de patrones (arch-agent)')
    expect(screen.getByTestId('citation-2')).not.toHaveTextContent('patrón principal')
  })

  it('explica por qué la propuesta no cita patrones', async () => {
    await renderWithProposal(proposalOut({
      citations,
      justification: { ...justification, cites_patterns: false, declared_primary: null, primary_in_sources: false },
    }))

    expect(screen.getByTestId('justification-status')).toHaveTextContent('no declara la línea “Patrón principal”')
  })

  it('"Verificar fuente" carga el patrón completo', async () => {
    const user = userEvent.setup()
    vi.mocked(getPatternDetail).mockResolvedValue({
      id: 3,
      pattern_name: 'Monolito modular',
      category: 'Monolítica',
      description: 'Un solo despliegue con módulos de dominio aislados',
      use_cases: null,
      tradeoffs: { ventajas: ['simple de operar'], desventajas: ['escala en bloque'] },
      when_not_to_use: null,
      decision_signals: null,
      chunks: [{ id: 1, chunk_type: 'summary', chunk_text: 'resumen', source: 'Catálogo curado de patrones (arch-agent)' }],
    })
    await renderWithProposal(proposalOut({ citations, justification }))

    const [verify] = screen.getAllByRole('button', { name: 'Verificar fuente' })
    await user.click(verify)

    expect(getPatternDetail).toHaveBeenCalledWith(3)
    const detail = await screen.findByTestId('pattern-detail')
    expect(detail).toHaveTextContent('Ventajas: simple de operar')
    expect(detail).toHaveTextContent('Fuentes indexadas: Catálogo curado de patrones (arch-agent)')
    expect(screen.getByRole('button', { name: 'Ocultar fuente' })).toHaveAttribute('aria-expanded', 'true')
  })
})
