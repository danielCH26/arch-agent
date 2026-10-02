import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ElicitationPanel } from '../ElicitationPanel'
import { getElicitationState, sendElicitationMessage } from '../../api/elicitation'

vi.mock('../../api/elicitation', () => ({
  getElicitationState: vi.fn(),
  sendElicitationMessage: vi.fn(),
  decideElicitation: vi.fn(),
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
})
