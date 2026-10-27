import { describe, expect, it } from 'vitest'
import { buildAdrPrintDocument } from '../adrPrint'
import { ADR_PALETTE } from '../adrTheme'

// HTML como lo arma el panel (renderMarkdownBlocks): '#' -> h3, '##' -> h4, '###' -> h5.
const BODY = `
  <h3 class="mb-2">ADR-001: Arquitectura de Analítica Académica</h3>
  <div class="my-3"><table><thead><tr><th>Campo</th><th>Valor</th></tr></thead><tbody>
    <tr><td>Estado</td><td>Aceptado</td></tr>
    <tr><td>Fecha</td><td>2026-10-22</td></tr>
    <tr><td>Proyecto</td><td>Analítica Académica</td></tr>
  </tbody></table></div>
  <blockquote><p>Este documento reúne las decisiones tomadas en cada fase.</p></blockquote>
  <h4>Resumen ejecutivo</h4>
  <p><strong>Qué problema resuelve:</strong> deserción.</p>
  <p><strong>Qué se decidió:</strong> monolito modular.</p>
  <h4>1. Contexto</h4><p>Texto</p>
  <h4>2. Requerimientos</h4><p>Texto</p>
  <h4>3. Decisión</h4><p>Texto</p>
  <h4>7. Guía para empezar</h4>
  <blockquote><p><strong>Revisión automática:</strong> cifra sin origen.</p></blockquote>
  <h5>7.1 Componentes y responsabilidades</h5><p>Texto</p>
  <h5>Funcionalidades</h5>
  <h4>Anexo A. Elicitación de requerimientos</h4><p>Texto</p>
`

function render(body = BODY) {
  const html = buildAdrPrintDocument(body, { title: 'ADR-analitica', baseHref: 'http://localhost' })
  return { html, doc: new DOMParser().parseFromString(html, 'text/html') }
}

describe('buildAdrPrintDocument', () => {
  it('arma una portada con el proyecto, el estado y los datos', () => {
    const { doc, html } = render()
    const cover = doc.querySelector('.cover')!
    expect(cover.querySelector('h1')?.textContent).toBe('Arquitectura de Analítica Académica')
    expect(cover.querySelector('.eyebrow')?.textContent).toBe('ADR-001')
    expect(cover.querySelector('.badge.ok')?.textContent).toBe('Aceptado')
    expect(cover.querySelector('.cover-meta')?.textContent).toContain('2026-10-22')
    expect(cover.querySelector('.cover-note')?.textContent).toContain('decisiones tomadas')
    // La tabla de datos y la introducción ya no se repiten en el cuerpo.
    expect(doc.querySelector('main table')).toBeNull()
    expect(doc.querySelector('main')?.textContent).not.toContain('decisiones tomadas')
    expect(html).toContain('<title>ADR-analitica</title>')
  })

  it('un ADR sin aprobar muestra el estado en ámbar', () => {
    const { doc } = render(BODY.replace('<td>Aceptado</td>', '<td>Propuesto (pendiente de aprobación)</td>'))
    const badge = doc.querySelector('.badge')!
    expect(badge.classList.contains('ok')).toBe(false)
    expect(badge.textContent).toContain('Propuesto')
  })

  it('tabla de contenido con capítulos y subsecciones numeradas que enlazan', () => {
    const { doc } = render()
    const items = Array.from(doc.querySelectorAll('.toc li')).map((li) => li.textContent)
    expect(items).toEqual([
      'Resumen ejecutivo',
      '1. Contexto',
      '2. Requerimientos',
      '3. Decisión',
      '7. Guía para empezar',
      '7.1 Componentes y responsabilidades',
      'Anexo A. Elicitación de requerimientos',
    ])
    const link = doc.querySelector('.toc a')!.getAttribute('href')!
    expect(doc.getElementById(link.slice(1))?.textContent).toBe('Resumen ejecutivo')
  })

  it('los capítulos grandes empiezan en página nueva y los cortos no', () => {
    const { doc } = render()
    const breaks = Array.from(doc.querySelectorAll('main h4.page-break')).map((h) => h.textContent)
    expect(breaks).toEqual([
      'Resumen ejecutivo',
      '1. Contexto',
      '3. Decisión',
      '7. Guía para empezar',
      'Anexo A. Elicitación de requerimientos',
    ])
  })

  it('el resumen ejecutivo va en un recuadro y la revisión automática en ámbar', () => {
    const { doc } = render()
    expect(doc.querySelector('.exec')?.textContent).toContain('monolito modular')
    expect(doc.querySelector('.exec')?.textContent).not.toContain('Texto')
    expect(doc.querySelector('blockquote.warn')?.textContent).toContain('cifra sin origen')
  })

  it('usa la paleta azul y las tipografías de la identidad del ADR', () => {
    const { html, doc } = render()
    expect(html).toContain(ADR_PALETTE.navy)
    expect(html).toContain(ADR_PALETTE.primary)
    expect(html).toContain("'Plus Jakarta Sans'")
    expect(doc.querySelector('link[rel="stylesheet"]')?.getAttribute('href')).toContain('fonts.googleapis.com')
    // Sin los índigos de antes.
    expect(html).not.toMatch(/#3730a3|#4f46e5|#eef2ff/i)
    expect(doc.querySelector('.cover .cover-band .brand')?.textContent).toBe('ArchAgent')
  })

  it('sin introducción, la portada lleva la decisión en una línea', () => {
    const { doc } = render(BODY.replace(/<blockquote><p>Este documento[\s\S]*?<\/blockquote>/, ''))
    expect(doc.querySelector('.cover-note')?.textContent).toContain('monolito modular')
  })

  it('quita las clases del panel y pone número de página en el pie', () => {
    const { doc, html } = render()
    expect(doc.querySelector('main [class*="mb-2"]')).toBeNull()
    expect(html).toContain('counter(page)')
    expect(html).toContain('<base href="http://localhost/">')
  })
})
