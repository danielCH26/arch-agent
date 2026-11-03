import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { DeploymentPanel } from '../DeploymentPanel'
import {
  decideDeployment,
  fetchDeploymentHistory,
  generateDeployment,
  listCloudProviders,
  type DeploymentPlan,
} from '../../api/deployments'

vi.mock('../../api/deployments', () => ({
  decideDeployment: vi.fn(),
  fetchDeploymentHistory: vi.fn(),
  generateDeployment: vi.fn(),
  listCloudProviders: vi.fn(),
}))

const providersMock = vi.mocked(listCloudProviders)
const generateMock = vi.mocked(generateDeployment)
const decideMock = vi.mocked(decideDeployment)
const historyMock = vi.mocked(fetchDeploymentHistory)

const PLAN = {
  attachment_id: 'dep-1',
  provider: { id: 'aws', name: 'Amazon Web Services', short_name: 'AWS', color: '#f90' },
  components: [
    {
      component: 'Backend API',
      service_id: 'ecs',
      service_name: 'Amazon ECS',
      deploy_note: 'Sube la imagen a ECR.',
      matched_term: 'backend',
    },
  ],
  services: [],
  connections: [],
  bridges: [],
  externals: [],
  unmapped: [],
  dropped_connections: [],
  url: '/api/chat/attachments/dep-1?token=x',
  render_error: null,
} as unknown as DeploymentPlan

beforeEach(() => {
  vi.clearAllMocks()
  providersMock.mockResolvedValue({
    providers: [
      { id: 'aws', name: 'Amazon Web Services', short_name: 'AWS', color: '#f90', service_count: 23 },
    ] as never,
  })
  generateMock.mockResolvedValue(PLAN)
  decideMock.mockResolvedValue({ decision: 'approve', message: 'ok' })
  historyMock.mockResolvedValue([])
})

async function aprobar() {
  await userEvent.click(screen.getByTestId('deployment-generate'))
  await waitFor(() => expect(screen.getByTestId('deployment-approve')).toBeInTheDocument())
  await userEvent.click(screen.getByTestId('deployment-approve'))
}

describe('DeploymentPanel: cierre de fase', () => {
  it('ofrece reintentar cuando el cierre de fase falla', async () => {
    // El caso que motivó separar `closePhase` de `handleDecision`: son DOS
    // llamadas y la segunda puede fallar sola. Si el panel se tragara el
    // error, el botón Aprobar ya no estaría y el proyecto se quedaría
    // trabado en Refinamiento.
    const onApproved = vi.fn().mockRejectedValueOnce(new Error('fase no cerrada'))
    render(
      <DeploymentPanel projectId={1} architectureApproved onApproved={onApproved} />,
    )
    await aprobar()

    await waitFor(() =>
      expect(screen.getByTestId('deployment-retry-close')).toBeInTheDocument(),
    )
    expect(screen.getByTestId('deployment-error')).toHaveTextContent('no se pudo cerrar la fase')
  })

  it('el reintento solo reintenta el cierre, no la decisión', async () => {
    // Repetir la decisión daría 409: la decisión sobre el diagrama ya quedó
    // registrada en el primer intento.
    const onApproved = vi
      .fn()
      .mockRejectedValueOnce(new Error('fase no cerrada'))
      .mockResolvedValueOnce(undefined)
    render(
      <DeploymentPanel projectId={1} architectureApproved onApproved={onApproved} />,
    )
    await aprobar()

    await waitFor(() =>
      expect(screen.getByTestId('deployment-retry-close')).toBeInTheDocument(),
    )
    expect(decideMock).toHaveBeenCalledTimes(1)

    await userEvent.click(screen.getByTestId('deployment-retry-close'))
    await waitFor(() => expect(onApproved).toHaveBeenCalledTimes(2))
    // La decisión NO se repitió.
    expect(decideMock).toHaveBeenCalledTimes(1)
  })

  it('tras un reintento exitoso ya no ofrece reintentar', async () => {
    const onApproved = vi
      .fn()
      .mockRejectedValueOnce(new Error('fase no cerrada'))
      .mockResolvedValueOnce(undefined)
    render(
      <DeploymentPanel projectId={1} architectureApproved onApproved={onApproved} />,
    )
    await aprobar()
    await waitFor(() =>
      expect(screen.getByTestId('deployment-retry-close')).toBeInTheDocument(),
    )

    await userEvent.click(screen.getByTestId('deployment-retry-close'))
    await waitFor(() =>
      expect(screen.queryByTestId('deployment-retry-close')).not.toBeInTheDocument(),
    )
  })

  it('si el cierre va bien no aparece el botón de reintento', async () => {
    const onApproved = vi.fn().mockResolvedValue(undefined)
    render(
      <DeploymentPanel projectId={1} architectureApproved onApproved={onApproved} />,
    )
    await aprobar()

    await waitFor(() => expect(onApproved).toHaveBeenCalled())
    expect(screen.queryByTestId('deployment-retry-close')).not.toBeInTheDocument()
  })
})
