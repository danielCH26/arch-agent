import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ElicitationPanel } from '../ElicitationPanel'
import { getElicitationState, sendElicitationMessage } from '../../api/elicitation'
import { listDocuments } from '../../api/documents'

vi.mock('../../api/elicitation', () => ({
  getElicitationState: vi.fn(),
  sendElicitationMessage: vi.fn(),
  decideElicitation: vi.fn(),
}))

vi.mock('../../api/documents', () => ({
  listDocuments: vi.fn().mockResolvedValue([]),
  uploadDocument: vi.fn(),
  DuplicateFileError: class DuplicateFileError extends Error {},
}))

const ADJUSTMENT = '(ajuste solicitado por el usuario)'

describe('ElicitationPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('tras "Solicitar cambios" pide al agente el siguiente paso y muestra el ajuste como del usuario', async () => {
    // Estado que deja el backend después de una decisión "modify".
    vi.mocked(getElicitationState).mockResolvedValue({
      done: false,
      question: null,
      resumen: null,
      history: [
        { pregunta: '¿Qué problema resuelve?', respuesta: 'Reservas de un restaurante' },
        { pregunta: ADJUSTMENT, respuesta: 'Agrega pagos en línea' },
      ],
    })
    vi.mocked(sendElicitationMessage).mockResolvedValue({
      done: false,
      question: '¿Qué pasarela de pagos prefieres?',
      resumen: null,
      history: [],
    })

    render(<ElicitationPanel projectId={7} phaseReady={false} onPhaseReady={() => {}} />)

    await waitFor(() => expect(sendElicitationMessage).toHaveBeenCalledWith(7))
    expect(await screen.findByText('¿Qué pasarela de pagos prefieres?')).toBeInTheDocument()
  })

  it('no pide un paso extra si ya hay una pregunta pendiente', async () => {
    vi.mocked(getElicitationState).mockResolvedValue({
      done: false,
      question: '¿Cuántos usuarios tendrá?',
      resumen: null,
      history: [{ pregunta: ADJUSTMENT, respuesta: 'Agrega pagos en línea' }],
    })

    render(<ElicitationPanel projectId={7} phaseReady={false} onPhaseReady={() => {}} />)

    expect(await screen.findByText('¿Cuántos usuarios tendrá?')).toBeInTheDocument()
    // El ajuste se muestra como mensaje del usuario, no como pregunta.
    expect(screen.getByText('Ajuste solicitado')).toBeInTheDocument()
    expect(screen.queryByText(ADJUSTMENT)).not.toBeInTheDocument()
    expect(sendElicitationMessage).not.toHaveBeenCalled()
  })

  describe('documentos del proyecto', () => {
    const notStarted = { done: false, question: null, resumen: null, history: [] }
    const doc = (processed: boolean) => ({
      id: 1, filename: 'acta.pdf', file_type: 'pdf', file_size_bytes: 10, chunk_count: 1, version: 1, processed,
      created_at: '',
    })

    it('antes de empezar se pueden subir y se explica que el agente los usa', async () => {
      vi.mocked(getElicitationState).mockResolvedValue(notStarted)
      vi.mocked(listDocuments).mockResolvedValue([])

      render(<ElicitationPanel projectId={7} phaseReady={false} onPhaseReady={() => {}} />)

      expect(await screen.findByText('¿Tienes documentos del proyecto? (opcional)')).toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'Comenzar elicitación' })).toBeEnabled()
    })

    it('no deja empezar mientras un documento se procesa', async () => {
      vi.mocked(getElicitationState).mockResolvedValue(notStarted)
      vi.mocked(listDocuments).mockResolvedValue([doc(false)])

      render(<ElicitationPanel projectId={7} phaseReady={false} onPhaseReady={() => {}} />)

      expect(await screen.findByText('· procesando…')).toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'Esperando los documentos…' })).toBeDisabled()
    })

    it('durante la elicitación muestra los documentos y deja adjuntar con el clip', async () => {
      vi.mocked(getElicitationState).mockResolvedValue({ ...notStarted, question: '¿Qué problema resuelve?' })
      vi.mocked(listDocuments).mockResolvedValue([doc(true)])

      render(<ElicitationPanel projectId={7} phaseReady={false} onPhaseReady={() => {}} />)

      expect(await screen.findByText('Documentos que el agente tiene en cuenta:')).toBeInTheDocument()
      expect(screen.getByLabelText('Adjuntar archivo (PDF o MD)')).toBeInTheDocument()
    })
  })
})
