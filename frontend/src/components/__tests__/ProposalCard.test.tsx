import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ProposalCard } from '../ProposalCard'
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
  getProjectProposalState: vi.fn(),
  getProposal: vi.fn(),
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

    expect(decideProposal).toHaveBeenCalledWith(41, 'reject', undefined)
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
