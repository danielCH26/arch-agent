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

  describe('tablas de trade-offs', () => {
    const header = '| Opción | Ventajas | Desventajas | Complejidad/costo |\n| --- | --- | --- | --- |\n'

    it('convierte <br> dentro de una celda en salto de línea, no en texto literal', () => {
      const { container } = renderMarkdown(
        `${header}| Hexagonal | 1. Testeable.<br>2. Cambio de proveedor. | 1. Más código.<br />2. Curva de aprendizaje. | Media |\n| Modular | a | b | Baja |\n| Capas | a | b | Baja |`,
      )
      const table = container.querySelector('table') as HTMLTableElement
      expect(table.textContent).not.toMatch(/<br/i)
      expect(table.querySelectorAll('br')).toHaveLength(2)
      expect(table.querySelectorAll('tbody tr')).toHaveLength(3)
      expect(table).toHaveTextContent('2. Cambio de proveedor.')
    })

    it('mantiene un \\| escapado dentro de una sola celda', () => {
      const { container } = renderMarkdown(
        `${header}| Capas | Simple \\| rápida | Escala junto | Baja |\n| Modular | a | b | Media |\n| Hexagonal | a | b | Media |`,
      )
      const table = container.querySelector('table') as HTMLTableElement
      expect(table.querySelectorAll('thead th')).toHaveLength(4)
      expect(table.querySelectorAll('tbody tr')[0].querySelectorAll('td')).toHaveLength(4)
      expect(table).toHaveTextContent('Simple | rápida')
      expect(table.textContent).not.toMatch(/\\\|/)
    })

    it('el <br> dentro de negrita es salto de línea y dentro de código en línea es texto', () => {
      const { container } = renderMarkdown(
        `${header}| Capas | **Simple<br>y claro** | usa \`<br>\` literal | Baja |\n| Modular | a | b | Media |\n| Hexagonal | a | b | Media |`,
      )
      const table = container.querySelector('table') as HTMLTableElement
      expect(table.querySelectorAll('strong br')).toHaveLength(1)
      expect(table.querySelectorAll('code br')).toHaveLength(0)
      expect(table.querySelector('code')).toHaveTextContent('<br>')
    })

    it('fuera de las tablas el <br> sigue siendo un salto de línea', () => {
      const { container } = renderMarkdown('Uno<br>Dos')
      expect(container.textContent).not.toMatch(/<br/i)
      expect(container).toHaveTextContent('Uno')
      expect(container).toHaveTextContent('Dos')
    })
  })
})
