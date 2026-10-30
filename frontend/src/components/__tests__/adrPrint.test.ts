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
  <p><strong>Con qué recursos:</strong></p>
  <ul><li><strong>Presupuesto:</strong> 20000 USD</li><li><strong>Equipo:</strong> 3 personas</li><li><strong>Plazo:</strong> 4 meses</li></ul>
  <h4>1. Contexto</h4><p>Texto</p>
  <h4>2. Requerimientos</h4><p>Texto</p>
  <h5>Atributos de calidad</h5>
  <ul><li>Disponibilidad 99.5%</li><li>Seguridad <em>(propuesto por el agente, no lo pidió el usuario)</em></li></ul>
  <h4>3. Decisión</h4><p>Texto</p>
  <h5>Trade-offs y decisión</h5>
  <div class="overflow-x-auto"><table><thead><tr><th>Opción</th><th>Ventajas</th><th>Desventajas</th><th>Complejidad/costo</th></tr></thead><tbody>
    <tr><td>1. Monolito modular</td><td>Simple de operar</td><td>Escala por bloques</td><td>Baja</td></tr>
    <tr><td>2. Microservicios</td><td>Escala fina</td><td>Operación costosa</td><td>Alta</td></tr>
  </tbody></table></div>
  <ul><li>Recomendación: Monolito modular [1]</li></ul>
  <h4>4. Diagrama de arquitectura</h4>
  <figure><img src="/aprobado.png" alt="Diagrama"></figure>
  <h4>7. Guía para empezar</h4>
  <blockquote><p><strong>Revisión automática:</strong> cifra sin origen.</p></blockquote>
  <h5>7.1 Componentes y responsabilidades</h5><p>Texto</p>
  <h5>7.3 Consecuencias</h5>
  <p><strong>Positivas</strong></p><ul><li>Despliegue único</li></ul>
  <p><strong>Negativas / costos asumidos</strong></p><ul><li>Un solo punto de falla</li></ul>
  <h5>7.4 Riesgos y mitigaciones</h5>
  <table><thead><tr><th>Riesgo</th><th>Impacto</th><th>Probabilidad</th><th>Mitigación</th></tr></thead><tbody>
    <tr><td>Fuente de datos sin confirmar</td><td>alto</td><td>alta</td><td>Validarla en el sprint 1</td></tr>
    <tr><td>Rotación del equipo</td><td>bajo</td><td>baja</td><td>Documentar</td></tr>
  </tbody></table>
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
    expect(Array.from(doc.querySelectorAll('main td')).some((td) => td.textContent === 'Estado')).toBe(false)
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
      '4. Diagrama de arquitectura',
      '7. Guía para empezar',
      '7.1 Componentes y responsabilidades',
      '7.3 Consecuencias',
      '7.4 Riesgos y mitigaciones',
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
      '4. Diagrama de arquitectura',
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

  it('la portada resume la decisión y los recursos en tarjetas', () => {
    const { doc } = render(BODY.replace(/<blockquote><p>Este documento[\s\S]*?<\/blockquote>/, ''))
    const facts = Array.from(doc.querySelectorAll('.cover-facts .fact')).map((f) => [
      f.querySelector('.fact-label')?.textContent,
      f.querySelector('.fact-value')?.textContent,
    ])
    expect(facts).toEqual([
      ['Decisión', 'monolito modular'],
      ['Presupuesto', '20000 USD'],
      ['Equipo', '3 personas'],
      ['Plazo', '4 meses'],
    ])
    // La decisión ya está en su tarjeta: no se repite en la nota.
    expect(doc.querySelector('.cover-note')).toBeNull()
  })

  it('la portada lleva el logo, el robot y la miniatura del diagrama', () => {
    const { doc } = render()
    expect(doc.querySelector('.cover .brand img.brand-logo')?.getAttribute('src')).toContain('robot-avatar')
    // El robot va completo: cuerpo y brazo (el cuerpo trae el hueco del brazo vacío).
    expect(doc.querySelector('.cover .cover-robot img.robot-body')?.getAttribute('src')).toContain('robot-body')
    expect(doc.querySelector('.cover .cover-robot img.robot-arm')?.getAttribute('src')).toContain('wave-a-arm')
    expect(doc.querySelector('.cover-thumb img')?.getAttribute('src')).toBe('/aprobado.png')
    // Separador de capítulo: el logo pequeño en los capítulos que abren página.
    expect(doc.querySelectorAll('main h4.page-break img.chapter-logo').length).toBe(
      doc.querySelectorAll('main h4.page-break').length,
    )
  })

  it('los trade-offs van en una tarjeta por opción con la recomendada marcada', () => {
    const { doc } = render()
    expect(Array.from(doc.querySelectorAll('main th')).some((th) => th.textContent === 'Opción')).toBe(false)
    const cards = Array.from(doc.querySelectorAll('.options .option'))
    expect(cards.map((c) => c.querySelector('.option-name')?.textContent)).toEqual(['Monolito modular', 'Microservicios'])
    expect(cards[0].classList.contains('recommended')).toBe(true)
    expect(cards[0].querySelector('.badge')?.textContent).toBe('Recomendada')
    expect(cards[1].classList.contains('recommended')).toBe(false)
    expect(cards[0].querySelector('.pros')?.textContent).toContain('Simple de operar')
    expect(cards[0].querySelector('.cons')?.textContent).toContain('Escala por bloques')
    expect(cards[0].querySelector('.option-meta')?.textContent).toContain('Complejidad/costo')
  })

  it('los atributos de calidad van como chips', () => {
    const { doc } = render()
    const chips = Array.from(doc.querySelectorAll('.chips .chip'))
    expect(chips.map((c) => c.firstChild?.textContent)).toEqual(['Disponibilidad 99.5%', 'Seguridad'])
    expect(chips[1].querySelector('small')?.textContent).toBe('propuesto por el agente')
  })

  it('consecuencias positivas y negativas lado a lado', () => {
    const { doc } = render()
    const cols = Array.from(doc.querySelectorAll('.conseq .conseq-col'))
    expect(cols.map((c) => c.className)).toEqual(['conseq-col pos', 'conseq-col neg'])
    expect(cols[0].textContent).toContain('Despliegue único')
    expect(cols[1].textContent).toContain('Un solo punto de falla')
  })

  it('matriz de riesgos por impacto y probabilidad', () => {
    const { doc } = render()
    const cell = (row: number, col: number) =>
      doc.querySelectorAll('.risk-matrix tbody tr')[row].querySelectorAll('td')[col]
    expect(cell(0, 2).textContent).toBe('R1')
    expect(cell(0, 2).className).toBe('sev-high')
    expect(cell(2, 0).textContent).toBe('R2')
    expect(cell(2, 0).className).toBe('sev-low')
    expect(doc.querySelector('.risk-id')?.textContent).toBe('R1')
  })

  it('sin columna de probabilidad (ADR anteriores) no hay matriz', () => {
    const { doc } = render(BODY.replace(/<th>Probabilidad<\/th>|<td>(alta|baja)<\/td>/g, ''))
    expect(doc.querySelector('.risk-matrix')).toBeNull()
  })

  it('la revisión automática va como nota del agente con su avatar', () => {
    const { doc } = render()
    const note = doc.querySelector('blockquote.agent-note.warn')!
    expect(note.querySelector('img.agent-avatar')?.getAttribute('src')).toContain('robot-avatar')
    expect(note.querySelector('.agent-label')?.textContent).toBe('Nota del agente')
  })

  it('quita las clases del panel y pone número de página en el pie', () => {
    const { doc, html } = render()
    expect(doc.querySelector('main [class*="mb-2"]')).toBeNull()
    expect(html).toContain('counter(page)')
    expect(html).toContain('<base href="http://localhost/">')
  })
})
