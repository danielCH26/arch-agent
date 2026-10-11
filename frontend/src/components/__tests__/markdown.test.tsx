import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { renderMarkdownBlocks } from '../MessageBubble'

function renderMarkdown(content: string) {
  return render(<div>{renderMarkdownBlocks(content)}</div>)
}

describe('renderMarkdownBlocks', () => {
  it('reconoce viñetas con * y + además de -', () => {
    const { container } = renderMarkdown('* uno\n* dos\n+ tres')
    const items = container.querySelectorAll('ul > li')
    expect([...items].map((li) => li.textContent)).toEqual(['uno', 'dos', 'tres'])
    expect(container.querySelector('p')).toBeNull()
  })

  it('anida sublistas por sangría', () => {
    const { container } = renderMarkdown('- Capa web\n  - React\n  - Vite\n- Backend')
    const topItems = container.querySelectorAll(':scope > div > ul > li')
    expect(topItems).toHaveLength(2)
    const nested = topItems[0].querySelectorAll('ul > li')
    expect([...nested].map((li) => li.textContent)).toEqual(['React', 'Vite'])
  })

  it('respeta el número inicial de una lista numerada', () => {
    const { container } = renderMarkdown('3. tercero\n4. cuarto')
    expect(container.querySelector('ol')).toHaveAttribute('start', '3')
  })

  it('no confunde negrita al inicio de línea con una viñeta', () => {
    renderMarkdown('**Importante:** revisa esto')
    expect(screen.getByText('Importante:').tagName).toBe('STRONG')
    expect(document.querySelector('ul')).toBeNull()
  })

  it('renderiza cursiva y enlaces seguros', () => {
    renderMarkdown('Ver *nota* y [docs](https://example.com/docs)')
    expect(screen.getByText('nota').tagName).toBe('EM')
    const link = screen.getByRole('link', { name: 'docs' })
    expect(link).toHaveAttribute('href', 'https://example.com/docs')
    expect(link).toHaveAttribute('rel', 'noopener noreferrer')
  })

  it('no crea enlaces con esquemas peligrosos', () => {
    renderMarkdown('[clic](javascript:robarDatos)')
    expect(screen.queryByRole('link')).toBeNull()
    expect(screen.getByText('clic')).toBeInTheDocument()
  })

  it('no toma guiones bajos dentro de identificadores como cursiva', () => {
    renderMarkdown('Usa mi_variable_larga en el código')
    expect(document.querySelector('em')).toBeNull()
  })
})
