import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import type { Pattern } from '../../api/patterns'

// vi.mock se eleva por encima de los imports: los datos van en vi.hoisted.
const { basePattern, patterns } = vi.hoisted(() => {
  const basePattern: Pattern = {
    id: 1,
    pattern_name: 'Arquitectura hexagonal',
    category: 'Monolítica',
    description: 'Aísla el dominio con puertos y adaptadores.',
    use_cases: null,
    tradeoffs: null,
    when_not_to_use: null,
    image: '/pattern-images/hexagonal.svg',
    image_alt: 'Hexágono con el núcleo de la aplicación y sus adaptadores alrededor',
    image_source: {
      titulo: 'File:Hexagonal Architecture.svg (Wikimedia Commons)',
      autor: 'Cth027',
      licencia: 'CC BY-SA 4.0',
      url: 'https://commons.wikimedia.org/wiki/File:Hexagonal_Architecture.svg',
    },
  }
  const patterns: Pattern[] = [
    basePattern,
    { ...basePattern, id: 2, pattern_name: 'Patrón sin imagen', image: null, image_alt: null, image_source: null },
    { ...basePattern, id: 3, pattern_name: 'Eventos', image: '/pattern-images/event_driven.svg', image_alt: 'Productores que envían eventos a un canal y consumidores independientes',
      image_source: { ...basePattern.image_source, autor: 'Microsoft', licencia: 'CC BY 4.0', modificada: true } },
  ]
  return { basePattern, patterns }
})

vi.mock('../../api/patterns', () => ({
  listPatterns: vi.fn(() => Promise.resolve({ total: patterns.length, items: patterns })),
  listPatternSourceChunks: vi.fn(() => Promise.resolve([])),
}))

import { PatternsPage } from '../PatternsPage'

async function openPattern(name: string) {
  render(
    <MemoryRouter>
      <PatternsPage />
    </MemoryRouter>,
  )
  fireEvent.click(await screen.findByRole('button', { name: new RegExp(name) }))
}

describe('PatternsPage: imagen del patrón', () => {
  it('muestra la imagen con texto alternativo y su fuente junto a la descripción', async () => {
    await openPattern('Arquitectura hexagonal')

    const img = screen.getByRole('img', { name: basePattern.image_alt! })
    expect(img).toHaveAttribute('src', '/pattern-images/hexagonal.svg')
    expect(screen.getByText('Aísla el dominio con puertos y adaptadores.', { selector: 'article p' })).toBeInTheDocument()
    const sourceLink = screen.getByRole('link', { name: /Wikimedia Commons/ })
    expect(sourceLink).toHaveAttribute('href', basePattern.image_source!.url)
    expect(screen.getByText(/Cth027 · CC BY-SA 4.0/)).toBeInTheDocument()
  })

  it('avisa cuando la imagen no carga sin romper el detalle', async () => {
    await openPattern('Arquitectura hexagonal')

    fireEvent.error(screen.getByRole('img', { name: basePattern.image_alt! }))

    expect(screen.getByRole('status')).toHaveTextContent('No se pudo cargar la imagen')
    expect(screen.queryByRole('img')).not.toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Arquitectura hexagonal' })).toBeInTheDocument()
  })

  it('al cambiar de patrón no arrastra el aviso de la imagen que no cargó', async () => {
    await openPattern('Arquitectura hexagonal')
    fireEvent.error(screen.getByRole('img', { name: basePattern.image_alt! }))
    expect(screen.getByRole('status')).toHaveTextContent('No se pudo cargar la imagen')

    fireEvent.click(screen.getByRole('button', { name: /Eventos/ }))

    expect(screen.getByRole('img', { name: /Productores que envían eventos/ })).toBeInTheDocument()
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
    // Imagen adaptada: CC BY exige indicarlo.
    expect(screen.getByText(/Microsoft · CC BY 4.0, adaptada/)).toBeInTheDocument()
  })

  it('avisa cuando el patrón todavía no tiene imagen', async () => {
    await openPattern('Patrón sin imagen')

    expect(screen.getByRole('status')).toHaveTextContent('todavía no tiene una imagen')
    expect(screen.queryByRole('img')).not.toBeInTheDocument()
  })
})
