import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { RepoStructurePanel } from '../RepoStructurePanel'
import {
  fetchRepoStructureHistory,
  generateRepoStructure,
  type StructurePlan,
} from '../../api/repoStructure'

vi.mock('../../api/repoStructure', () => ({
  fetchRepoStructureHistory: vi.fn(),
  generateRepoStructure: vi.fn(),
}))

const historyMock = vi.mocked(fetchRepoStructureHistory)
const generateMock = vi.mocked(generateRepoStructure)

const PLAN: StructurePlan = {
  attachment_id: 'str-1',
  backend: {
    convention_id: 'fastapi',
    name: 'FastAPI (backend Python)',
    summary: 'Agrupa el código como un paquete Python.',
    matched_term: 'fastapi',
    nesting_limit: null,
    fuentes: [{ titulo: 'Bigger Applications', url: 'https://fastapi.tiangolo.com/x' }],
  },
  frontend: null,
  modules: [
    {
      name: 'Gestion de pedidos',
      kind: 'crud',
      matched_term: 'gestion',
      origin: 'diagrama',
      uncovered_reason: '',
      patterns: [
        {
          pattern_name: 'Repository',
          role: 'repository',
          justification: 'Carpeta de repositorios: una clase por entidad.',
          matched_kind: 'crud',
          source_title: 'Repository (Martin Fowler)',
          source_url: 'https://martinfowler.com/eaaCatalog/repository.html',
          path: 'app/repositories/gestion_de_pedidos.py',
          placed: true,
        },
      ],
    },
    {
      name: 'Notificaciones por correo',
      kind: 'notificaciones',
      matched_term: 'notificaciones',
      origin: 'diagrama',
      uncovered_reason: 'No hay en la base ningún patrón aplicable a este tipo.',
      patterns: [],
    },
  ],
  lines: [
    {
      path: 'app/main.py',
      note: 'Módulo de entrada.',
      origin: 'convencion',
      pattern_name: '',
      role: '',
      module: '',
      source_title: 'Bigger Applications',
      source_url: 'https://fastapi.tiangolo.com/x',
    },
    {
      path: 'app/repositories/gestion_de_pedidos.py',
      note: 'Carpeta de repositorios.',
      origin: 'patron',
      pattern_name: 'Repository',
      role: 'repository',
      module: 'Gestion de pedidos',
      source_title: 'Repository (Martin Fowler)',
      source_url: 'https://martinfowler.com/eaaCatalog/repository.html',
    },
  ],
  tree_text: 'app/\n    repositories/\n        gestion_de_pedidos.py\n    main.py',
  warnings: ['Notificaciones por correo: sin patrón aplicable.'],
  unmatched_layers: [],
  module_kinds: ['crud', 'notificaciones'],
}

beforeEach(() => {
  vi.clearAllMocks()
  historyMock.mockResolvedValue([])
  generateMock.mockResolvedValue(PLAN)
})

describe('RepoStructurePanel', () => {
  it('sin diagrama aprobado explica qué falta y no ofrece generar', () => {
    render(<RepoStructurePanel projectId={1} architectureApproved={false} />)
    expect(screen.getByTestId('repo-structure-blocked')).toBeInTheDocument()
    expect(screen.queryByTestId('repo-structure-generate')).not.toBeInTheDocument()
  })

  it('no pide el historial mientras no haya diagrama aprobado', () => {
    render(<RepoStructurePanel projectId={1} architectureApproved={false} />)
    expect(historyMock).not.toHaveBeenCalled()
  })

  it('genera el árbol y lo muestra como texto', async () => {
    render(<RepoStructurePanel projectId={7} architectureApproved />)
    await userEvent.click(screen.getByTestId('repo-structure-generate'))

    await waitFor(() => expect(screen.getByTestId('repo-structure-tree')).toBeInTheDocument())
    expect(generateMock).toHaveBeenCalledWith(7)
    expect(screen.getByTestId('repo-structure-tree')).toHaveTextContent('repositories/')
  })

  it('cada línea del árbol enlaza su fuente', async () => {
    render(<RepoStructurePanel projectId={1} architectureApproved />)
    await userEvent.click(screen.getByTestId('repo-structure-generate'))

    await waitFor(() => expect(screen.getByTestId('repo-structure-lines')).toBeInTheDocument())
    const enlaces = screen
      .getByTestId('repo-structure-lines')
      .querySelectorAll('a[href^="http"]')
    // Una por línea: ninguna puede quedar sin fuente.
    expect(enlaces).toHaveLength(PLAN.lines.length)
  })

  it('distingue lo que trae la convención de lo que aporta un patrón', async () => {
    render(<RepoStructurePanel projectId={1} architectureApproved />)
    await userEvent.click(screen.getByTestId('repo-structure-generate'))

    await waitFor(() => expect(screen.getByTestId('repo-structure-lines')).toBeInTheDocument())
    const tabla = screen.getByTestId('repo-structure-lines')
    expect(tabla).toHaveTextContent('Convención del stack')
    expect(tabla).toHaveTextContent('Repository')
  })

  it('muestra el patrón de cada módulo con su razón al desplegarlo', async () => {
    render(<RepoStructurePanel projectId={1} architectureApproved />)
    await userEvent.click(screen.getByTestId('repo-structure-generate'))

    await waitFor(() => expect(screen.getByTestId('repo-structure-modules')).toBeInTheDocument())
    await userEvent.click(screen.getByRole('button', { name: /Gestion de pedidos/ }))
    expect(screen.getByText(/una clase por entidad/)).toBeInTheDocument()
  })

  it('dice cuando un módulo no tiene patrón aplicable', async () => {
    render(<RepoStructurePanel projectId={1} architectureApproved />)
    await userEvent.click(screen.getByTestId('repo-structure-generate'))

    await waitFor(() => expect(screen.getByTestId('repo-structure-modules')).toBeInTheDocument())
    await userEvent.click(screen.getByRole('button', { name: /Notificaciones por correo/ }))
    expect(screen.getByText(/ningún patrón aplicable/)).toBeInTheDocument()
  })

  it('muestra el término que decidió el tipo de módulo', async () => {
    render(<RepoStructurePanel projectId={1} architectureApproved />)
    await userEvent.click(screen.getByTestId('repo-structure-generate'))

    await waitFor(() => expect(screen.getByTestId('repo-structure-modules')).toBeInTheDocument())
    expect(screen.getByTestId('repo-structure-modules')).toHaveTextContent('por «gestion»')
  })

  it('lista las advertencias', async () => {
    render(<RepoStructurePanel projectId={1} architectureApproved />)
    await userEvent.click(screen.getByTestId('repo-structure-generate'))

    await waitFor(() => expect(screen.getByTestId('repo-structure-warnings')).toBeInTheDocument())
    expect(screen.getByTestId('repo-structure-warnings')).toHaveTextContent(
      'sin patrón aplicable',
    )
  })

  it('muestra el error del servidor sin romper el panel', async () => {
    generateMock.mockRejectedValue(new Error('Aprueba primero el diagrama'))
    render(<RepoStructurePanel projectId={1} architectureApproved />)
    await userEvent.click(screen.getByTestId('repo-structure-generate'))

    await waitFor(() => expect(screen.getByTestId('repo-structure-error')).toBeInTheDocument())
    expect(screen.getByTestId('repo-structure-error')).toHaveTextContent(
      'Aprueba primero el diagrama',
    )
    // El botón sigue disponible para reintentar.
    expect(screen.getByTestId('repo-structure-generate')).toBeEnabled()
  })

  it('un historial que falla no rompe el panel', async () => {
    historyMock.mockRejectedValue(new Error('500'))
    render(<RepoStructurePanel projectId={1} architectureApproved />)
    expect(screen.getByTestId('repo-structure-generate')).toBeInTheDocument()
    await waitFor(() => expect(historyMock).toHaveBeenCalled())
  })

  it('lista las versiones generadas', async () => {
    historyMock.mockResolvedValue([
      {
        message_id: 3,
        id: 'str-1',
        created_at: '2024-05-01T10:00:00+00:00',
        backend_name: 'FastAPI (backend Python)',
        frontend_name: null,
        module_count: 4,
        tree_text: 'app/',
        plan: {},
      },
    ])
    render(<RepoStructurePanel projectId={1} architectureApproved />)
    await waitFor(() => expect(screen.getByTestId('repo-structure-history')).toBeInTheDocument())
    expect(screen.getByTestId('repo-structure-history')).toHaveTextContent('4 módulos')
  })

  it('refresca el historial después de generar', async () => {
    render(<RepoStructurePanel projectId={1} architectureApproved />)
    await waitFor(() => expect(historyMock).toHaveBeenCalledTimes(1))
    await userEvent.click(screen.getByTestId('repo-structure-generate'))
    await waitFor(() => expect(historyMock).toHaveBeenCalledTimes(2))
  })
})
