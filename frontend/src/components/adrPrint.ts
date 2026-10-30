// Versión imprimible del ADR (lo que se guarda como PDF).
//
// El ADR es el entregable del proyecto: lo que se le pasa a la empresa o al
// cliente. Antes el PDF era el markdown impreso tal cual; ahora se arma como
// un documento técnico: portada con la marca, el robot y un resumen visual
// (decisión, presupuesto, equipo, plazo y miniatura del diagrama), tabla de
// contenido, resumen ejecutivo destacado, cada capítulo grande en su propia
// página, encabezado y pie con número de página, trade-offs en tarjetas,
// atributos de calidad en chips, consecuencias separadas, matriz de riesgos y
// notas del agente con su avatar.
//
// Todo se hace sobre el HTML que ya renderiza el panel (mismo contenido que el
// .md), sin librerías ni backend. Colores y tipografías salen de adrTheme.ts;
// reglas de uso de logo y mascota en .atl/skills/adr-design/SKILL.md.

import robotAvatar from '../assets/robot-avatar.webp'
import robotBody from '../assets/robot-body.webp'
import waveArm from '../assets/wave-a-arm.webp'
import { ADR_FONTS, ADR_FONTS_HREF, ADR_PALETTE, ADR_SPACE, ADR_TYPE } from './adrTheme'
import { ARM_STYLE, ROBOT_ASPECT_RATIO } from './robotLayout'

export interface AdrPrintOptions {
  /** Título de la ventana; Chrome lo usa como nombre del PDF. */
  title: string
  /** Origen de la app, para que las imágenes con ruta relativa carguen. */
  baseHref?: string
}

const HTML_ESCAPES: Record<string, string> = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }

export function escapeHtml(text: string): string {
  return text.replace(/[&<>"]/g, (c) => HTML_ESCAPES[c] ?? c)
}

// Texto seguro dentro de `content: "..."` en CSS.
function cssString(text: string): string {
  return `"${text.replace(/\\/g, '\\\\').replace(/"/g, '\\"').replace(/[\r\n]+/g, ' ')}"`
}

// Capítulos que empiezan en página nueva. Los cortos (Contexto y
// Requerimientos, Referencias e Historial) van seguidos para no dejar
// páginas casi vacías.
const PAGE_BREAK_BEFORE = /^(resumen ejecutivo|1\.|3\.|4\.|7\.|anexo)/i

const C = ADR_PALETTE
const F = ADR_FONTS
const S = ADR_SPACE
const T = ADR_TYPE

// Identidad "ArchAgent Blueprint" (adrTheme.ts): azules para estructura y
// marca, neutros para el texto, verde/ámbar/rojo solo para estados.
const PRINT_STYLES = (runningTitle: string) => `
  @page {
    size: A4;
    margin: 22mm 18mm 20mm;
    @top-left { content: ${cssString(runningTitle)}; font: 600 8pt ${F.heading}; color: ${C.primary}; }
    @top-right { content: "Architecture Decision Record"; font: 8pt ${F.body}; color: ${C.muted}; }
    @bottom-left { content: "ArchAgent"; font: 700 8pt ${F.heading}; color: ${C.primary}; }
    @bottom-right { content: "Página " counter(page) " de " counter(pages); font: 8pt ${F.body}; color: ${C.muted}; }
  }
  @page :first {
    margin: 0;
    @top-left { content: none; } @top-right { content: none; }
    @bottom-left { content: none; } @bottom-right { content: none; }
  }
  * { box-sizing: border-box; }
  html { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  body { font-family: ${F.body}; color: ${C.ink}; line-height: 1.6; font-size: ${T.body}pt; margin: 0; }
  @media screen { body { max-width: 210mm; margin: 0 auto; padding: 16mm 18mm; background: #fff; } html { background: ${C.sky}; } }

  .print-note { font-size: 9pt; color: ${C.primary}; background: ${C.tint}; border: 1px solid ${C.sky}; border-radius: 6px; padding: 6pt 10pt; margin-bottom: 14pt; }
  @media print { .print-note { display: none; } }

  /* Portada: banda azul marino con marca y robot; debajo el resumen visual */
  .cover { height: 297mm; display: flex; flex-direction: column; break-after: page; background: #fff; overflow: hidden; }
  @media screen { .cover { height: auto; min-height: 250mm; margin: 0 -18mm 16mm; } }
  .cover-band { background: ${C.navy}; color: #fff; padding: 16mm 20mm 0; position: relative; }
  .cover-band::after { content: ""; position: absolute; left: 20mm; bottom: 0; width: 46mm; height: 5pt; background: ${C.accent}; }
  .cover-top { display: flex; justify-content: space-between; align-items: center; margin-bottom: 14mm; }
  .brand { display: inline-flex; align-items: center; gap: 7pt; font-family: ${F.heading}; font-weight: 800; font-size: 15pt; letter-spacing: .02em; color: #fff; }
  .brand span { color: ${C.accent}; }
  .brand-logo { height: 26pt; width: auto; }
  .doc-type { font-size: 8.5pt; color: ${C.sky}; text-transform: uppercase; letter-spacing: .14em; }
  .cover-hero { display: flex; align-items: flex-end; gap: 10mm; }
  .cover-main { flex: 1; padding-bottom: 14mm; }
  /* El cuerpo trae el hueco del brazo transparente: el brazo va en otra capa, como en la app */
  .cover-robot { position: relative; height: 62mm; aspect-ratio: ${ROBOT_ASPECT_RATIO}; flex: none; }
  .cover-robot img { position: absolute; display: block; }
  .cover-robot .robot-body { inset: 0; width: 100%; height: 100%; }
  .cover-robot .robot-arm { left: ${ARM_STYLE.left}; top: ${ARM_STYLE.top}; width: ${ARM_STYLE.width}; height: ${ARM_STYLE.height}; }
  .eyebrow { font-family: ${F.heading}; font-size: 10pt; font-weight: 700; color: ${C.accent}; text-transform: uppercase; letter-spacing: .16em; margin: 0 0 ${S.sm}pt; }
  .cover h1 { font-family: ${F.heading}; font-size: ${T.cover}pt; font-weight: 800; line-height: 1.12; color: #fff; margin: 0 0 ${S.md}pt; }
  .subtitle { font-size: 12.5pt; color: ${C.sky}; margin: 0 0 ${S.lg}pt; }
  .badge { display: inline-block; font-size: 9.5pt; font-weight: 600; padding: 4pt 12pt; border-radius: 999px; background: ${C.warning_bg}; color: ${C.warning}; }
  .badge.ok { background: ${C.success_bg}; color: ${C.success}; }
  .cover-body { padding: 12mm 20mm 14mm; display: flex; flex-direction: column; gap: 8mm; flex: 1; }
  .cover-facts { display: grid; grid-template-columns: repeat(3, 1fr); gap: ${S.sm}pt; }
  .fact { background: ${C.tint}; border: 1px solid ${C.sky}; border-top: 3px solid ${C.secondary}; border-radius: 6px; padding: ${S.sm}pt 10pt; }
  .fact.wide { grid-column: 1 / -1; border-top-color: ${C.primary}; }
  .fact-label { display: block; font-family: ${F.heading}; font-size: 7.5pt; font-weight: 700; color: ${C.secondary}; text-transform: uppercase; letter-spacing: .12em; margin-bottom: 2pt; }
  .fact-value { display: block; font-size: 10pt; font-weight: 600; color: ${C.navy}; line-height: 1.35; }
  .fact.wide .fact-value { font-family: ${F.heading}; font-size: 13pt; }
  .cover-row { display: flex; gap: 8mm; align-items: flex-start; }
  .cover-row > * { flex: 1; min-width: 0; }
  .cover-thumb { margin: 0; padding: ${S.sm}pt; border: 1px solid ${C.sky}; border-radius: 8px; text-align: center; }
  .cover-thumb img { max-height: 58mm; width: auto; max-width: 100%; }
  .cover-thumb figcaption { margin-top: 4pt; }
  .cover-meta { width: 100%; border-collapse: collapse; font-size: 9.5pt; margin: 0; border: 0; border-radius: 0; }
  .cover-meta th { width: 40%; text-align: left; font-weight: 600; color: ${C.primary}; background: transparent; border: 0; border-bottom: 1px solid ${C.line}; padding: 6pt 0; font-family: ${F.body}; }
  .cover-meta td { border: 0; border-bottom: 1px solid ${C.line}; padding: 6pt 0; color: ${C.ink}; background: transparent !important; }
  .cover-note { font-size: 9pt; color: ${C.muted}; border-left: 3px solid ${C.secondary}; padding: 2pt 0 2pt 10pt; }
  .cover-note p { margin: 0; }

  /* Contenido */
  .toc { break-after: page; }
  .toc h2 { font-family: ${F.heading}; font-size: 20pt; color: ${C.navy}; margin: 0 0 ${S.lg}pt; padding-bottom: 6pt; border-bottom: 3px solid ${C.primary}; }
  .toc ol { list-style: none; padding: 0; margin: 0; }
  .toc li { border-bottom: 1px dotted ${C.sky}; padding: 6pt 0; font-size: 11pt; font-weight: 600; color: ${C.navy}; }
  .toc li.sub { padding-left: 16pt; font-size: 9.5pt; font-weight: 400; color: ${C.muted}; border-bottom: 0; padding-top: 2pt; padding-bottom: 2pt; }
  .toc a { color: inherit; text-decoration: none; }

  h3, h4, h5, h6 { font-family: ${F.heading}; line-height: 1.25; break-after: avoid; }
  h4 { font-size: ${T.h4}pt; font-weight: 700; margin: 26pt 0 ${S.md}pt; padding: 0 0 6pt 12pt; color: ${C.navy}; border-left: 5px solid ${C.primary}; border-bottom: 1px solid ${C.sky}; }
  h4.page-break { break-before: page; margin-top: 0; }
  /* Separador de capítulo: el logo pequeño al final del título */
  .chapter-logo { float: right; height: 20pt; width: auto; margin: -3pt 0 0 ${S.sm}pt; }
  h5 { font-size: ${T.h5}pt; font-weight: 700; margin: ${S.lg}pt 0 6pt; color: ${C.primary}; }
  h6 { font-size: ${T.body}pt; font-weight: 700; margin: ${S.md}pt 0 ${S.xs}pt; color: ${C.secondary}; text-transform: uppercase; letter-spacing: .04em; }
  p, ul, ol { margin: 0 0 ${S.sm}pt; }
  ul { padding-left: 16pt; }
  li { margin-bottom: 3pt; break-inside: avoid; }
  li::marker { color: ${C.secondary}; }
  strong { color: ${C.navy}; font-weight: 600; }
  em { color: ${C.muted}; }

  table { border-collapse: separate; border-spacing: 0; width: 100%; margin: 6pt 0 ${S.md}pt; font-size: 9pt; border: 1px solid ${C.line}; border-radius: 6px; overflow: hidden; }
  thead { display: table-header-group; }
  tr, td, th { break-inside: avoid; }
  th, td { padding: 6pt 8pt; text-align: left; vertical-align: top; border-bottom: 1px solid ${C.line}; overflow-wrap: anywhere; }
  th { background: ${C.navy}; color: #fff; font-weight: 600; font-family: ${F.heading}; letter-spacing: .01em; }
  tbody tr:nth-child(even) td { background: ${C.paper}; }
  tbody tr:last-child td { border-bottom: 0; }

  pre, code { font-family: ${F.mono}; font-size: 8.5pt; }
  code { background: ${C.tint}; color: ${C.primary}; padding: 0 3pt; border-radius: 3px; }
  pre { background: ${C.paper}; border: 1px solid ${C.line}; border-left: 3px solid ${C.secondary}; border-radius: 4px; padding: ${S.sm}pt 10pt; white-space: pre-wrap; break-inside: avoid; }
  pre code { background: transparent; color: ${C.ink}; padding: 0; }
  blockquote { margin: 0 0 10pt; padding: ${S.sm}pt ${S.md}pt; border-left: 4px solid ${C.secondary}; background: ${C.tint}; border-radius: 0 4px 4px 0; break-inside: avoid; }
  blockquote.warn { border-left-color: ${C.warning}; background: ${C.warning_bg}; }
  blockquote p:last-child { margin-bottom: 0; }

  /* Nota del agente: el avatar del robot firma lo que escribió la revisión automática */
  .agent-note { display: flex; gap: 10pt; align-items: flex-start; }
  .agent-avatar { height: 28pt; width: auto; flex: none; }
  .agent-note-body { flex: 1; min-width: 0; }
  .agent-label { font-family: ${F.heading}; font-size: 7.5pt; font-weight: 700; text-transform: uppercase; letter-spacing: .12em; color: ${C.primary}; margin: 0 0 2pt; }
  blockquote.warn .agent-label { color: ${C.warning}; }

  .exec { background: ${C.tint}; border: 1px solid ${C.sky}; border-top: 4px solid ${C.primary}; border-radius: 6px; padding: ${S.md}pt 16pt; margin-bottom: ${S.sm}pt; }
  .exec p { margin-bottom: 6pt; }

  /* Atributos de calidad */
  .chips { display: flex; flex-wrap: wrap; gap: 6pt; margin: 0 0 ${S.md}pt; }
  .chip { display: inline-block; font-size: 9pt; font-weight: 600; color: ${C.primary}; background: ${C.tint}; border: 1px solid ${C.sky}; border-radius: 999px; padding: 3pt 10pt; }
  .chip small { font-weight: 400; color: ${C.muted}; margin-left: 4pt; }

  /* Trade-offs: una tarjeta por opción */
  .options { display: flex; flex-direction: column; gap: ${S.sm}pt; margin: 6pt 0 ${S.md}pt; }
  .option { border: 1px solid ${C.line}; border-left: 4px solid ${C.sky}; border-radius: 6px; padding: ${S.sm}pt ${S.md}pt; break-inside: avoid; }
  .option.recommended { border-left-color: ${C.success}; background: ${C.paper}; }
  .option-head { display: flex; justify-content: space-between; align-items: center; gap: ${S.sm}pt; margin-bottom: 6pt; }
  .option-name { font-family: ${F.heading}; font-size: 11.5pt; font-weight: 700; color: ${C.navy}; margin: 0; }
  .option-head .badge { font-size: 8pt; padding: 2pt 9pt; flex: none; }
  .option-grid { display: grid; grid-template-columns: 1fr 1fr; gap: ${S.md}pt; font-size: 9.5pt; }
  .option-label { font-family: ${F.heading}; font-size: 7.5pt; font-weight: 700; text-transform: uppercase; letter-spacing: .12em; margin: 0 0 2pt; }
  .pros .option-label { color: ${C.success}; }
  .cons .option-label { color: ${C.danger}; }
  .option-meta { display: grid; grid-template-columns: max-content 1fr; gap: 2pt ${S.md}pt; margin: 6pt 0 0; padding-top: 6pt; border-top: 1px dashed ${C.line}; font-size: 9pt; }
  .option-meta dt { font-weight: 600; color: ${C.primary}; }
  .option-meta dd { margin: 0; }

  /* Consecuencias positivas y negativas lado a lado */
  .conseq { display: grid; grid-template-columns: 1fr 1fr; gap: ${S.md}pt; margin: 0 0 ${S.md}pt; }
  .conseq-col { border-radius: 6px; padding: ${S.sm}pt ${S.md}pt; break-inside: avoid; }
  .conseq-col.pos { background: ${C.success_bg}; border-top: 3px solid ${C.success}; }
  .conseq-col.neg { background: ${C.danger_bg}; border-top: 3px solid ${C.danger}; }
  .conseq-col ul { margin: 0; }
  .conseq-col.pos .option-label { color: ${C.success}; }
  .conseq-col.neg .option-label { color: ${C.danger}; }

  /* Matriz de riesgos: impacto (filas) x probabilidad (columnas) */
  .risk-matrix { break-inside: avoid; margin: 6pt 0 ${S.md}pt; }
  .risk-matrix table { table-layout: fixed; width: auto; min-width: 60%; }
  .risk-matrix th, .risk-matrix td { text-align: center; vertical-align: middle; height: 26pt; font-weight: 700; }
  .risk-matrix tbody th { background: ${C.paper}; color: ${C.navy}; text-align: left; }
  .risk-matrix td.sev-high { background: ${C.danger_bg} !important; color: ${C.danger}; }
  .risk-matrix td.sev-mid { background: ${C.warning_bg} !important; color: ${C.warning}; }
  .risk-matrix td.sev-low { background: ${C.success_bg} !important; color: ${C.success}; }
  .risk-id { display: inline-block; font-family: ${F.heading}; font-weight: 700; color: ${C.primary}; margin-right: 4pt; }

  img { max-width: 100%; height: auto; }
  figure { margin: ${S.sm}pt 0 ${S.md}pt; text-align: center; break-inside: avoid; border: 1px solid ${C.sky}; border-radius: 8px; padding: ${S.md}pt; background: #fff; }
  figcaption { font-size: ${T.small}pt; color: ${C.muted}; margin-top: 6pt; }
  figcaption strong { color: ${C.primary}; }
  a { color: ${C.primary}; }
`

function isBefore(node: Node, reference: Node | null): boolean {
  if (!reference) return true
  return Boolean(node.compareDocumentPosition(reference) & Node.DOCUMENT_POSITION_FOLLOWING)
}

function text(node: Element | null | undefined): string {
  return (node?.textContent ?? '').replace(/\s+/g, ' ').trim()
}

function normalize(value: string): string {
  return value
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/\[\d+\]|[*_`]/g, '')
    .replace(/^\d+\.\s*/, '')
    .toLowerCase()
    .trim()
}

function shorten(value: string, limit = 90): string {
  return value.length <= limit ? value : `${value.slice(0, limit).replace(/\s+\S*$/, '')}…`
}

// Quita la tabla y su envoltorio con scroll horizontal (un <div> con solo la tabla).
function tableBox(table: Element, root: Element): Element {
  const wrapper = table.parentElement
  return wrapper && wrapper !== root && wrapper.children.length === 1 ? wrapper : table
}

// Hermanos de un título hasta el siguiente título del mismo nivel o superior.
function sectionSiblings(heading: Element): Element[] {
  const stop = heading.tagName === 'H5' ? /^H[345]$/ : /^H[34]$/
  const items: Element[] = []
  for (let next = heading.nextElementSibling; next && !stop.test(next.tagName); next = next.nextElementSibling) {
    items.push(next)
  }
  return items
}

function findHeading(root: Element, selector: string, pattern: RegExp): Element | undefined {
  return Array.from(root.querySelectorAll(selector)).find((el) => pattern.test(text(el)))
}

function headerCells(table: Element): string[] {
  const row = table.querySelector('thead tr') ?? table.querySelector('tr')
  return Array.from(row?.querySelectorAll('th, td') ?? []).map((cell) => normalize(text(cell)))
}

function bodyRows(table: Element): Element[][] {
  const rows = table.querySelector('thead') ? table.querySelectorAll('tbody tr') : table.querySelectorAll('tr:not(:first-child)')
  return Array.from(rows).map((row) => Array.from(row.querySelectorAll('td')))
}

// Trade-offs de la propuesta: la tabla de 6 columnas se partía en tiras de
// 2-3 palabras y entre páginas. Se reemplaza por una tarjeta por opción, con
// la recomendada marcada.
function tradeoffCards(doc: Document, root: Element): void {
  const recommendation = Array.from(root.querySelectorAll('li, p'))
    .map((el) => text(el).match(/^recomendaci[oó]n:\s*(.+)$/i)?.[1] ?? '')
    .find(Boolean)
  const recommended = recommendation ? normalize(recommendation) : ''
  root.querySelectorAll('table').forEach((table) => {
    const headers = headerCells(table)
    if (!/^opcion/.test(headers[0] ?? '') || !headers.some((h) => h.startsWith('ventajas'))) return
    const labels = Array.from((table.querySelector('thead tr') ?? table.querySelector('tr'))!.children).map((cell) => cell.innerHTML)
    const cards = doc.createElement('div')
    cards.className = 'options'
    bodyRows(table).forEach((cells) => {
      if (!cells.length) return
      const name = normalize(text(cells[0]))
      const isRecommended = Boolean(name && recommended && (recommended.includes(name) || name.includes(recommended)))
      const column = (prefix: string) => cells[headers.findIndex((h) => h.startsWith(prefix))]
      const pros = column('ventajas')
      const cons = column('desventajas')
      const rest = cells
        .map((cell, index) => ({ cell, index }))
        .filter(({ cell, index }) => index > 0 && cell !== pros && cell !== cons && text(cell))
      const card = doc.createElement('article')
      card.className = `option${isRecommended ? ' recommended' : ''}`
      card.innerHTML =
        `<div class="option-head"><p class="option-name">${cells[0].innerHTML.trim().replace(/^\d+\.\s*/, '')}</p>` +
        (isRecommended ? '<span class="badge ok">Recomendada</span>' : '') +
        `</div><div class="option-grid">` +
        `<div class="pros"><p class="option-label">Ventajas</p>${pros?.innerHTML ?? '—'}</div>` +
        `<div class="cons"><p class="option-label">Desventajas</p>${cons?.innerHTML ?? '—'}</div></div>` +
        (rest.length
          ? `<dl class="option-meta">${rest
              .map(({ cell, index }) => `<dt>${labels[index] ?? ''}</dt><dd>${cell.innerHTML}</dd>`)
              .join('')}</dl>`
          : '')
      cards.appendChild(card)
    })
    tableBox(table, root).replaceWith(cards)
  })
}

// Atributos de calidad como chips; los que propuso el agente llevan la marca.
function qualityChips(doc: Document, root: Element): void {
  const heading = findHeading(root, 'h5', /^atributos de calidad$/i)
  const list = heading?.nextElementSibling
  if (!list || list.tagName !== 'UL') return
  const chips = doc.createElement('div')
  chips.className = 'chips'
  list.querySelectorAll(':scope > li').forEach((li) => {
    const note = Array.from(li.querySelectorAll('em')).find((em) => /propuesto por el agente/i.test(text(em)))
    note?.remove()
    const chip = doc.createElement('span')
    chip.className = 'chip'
    chip.innerHTML = li.innerHTML.trim() + (note ? '<small>propuesto por el agente</small>' : '')
    chips.appendChild(chip)
  })
  list.replaceWith(chips)
}

// 7.3 Consecuencias: las listas "Positivas" y "Negativas" lado a lado.
function consequenceColumns(doc: Document, root: Element): void {
  const heading = findHeading(root, 'h5', /^7\.3\s/)
  if (!heading) return
  const siblings = sectionSiblings(heading)
  const columns: Array<{ kind: 'pos' | 'neg'; label: Element; list: Element }> = []
  siblings.forEach((el) => {
    const kind = /^positiv/i.test(text(el)) ? 'pos' : /^negativ/i.test(text(el)) ? 'neg' : null
    const list = el.nextElementSibling
    if (kind && /^(P|H6)$/.test(el.tagName) && list && /^(UL|OL)$/.test(list.tagName)) columns.push({ kind, label: el, list })
  })
  if (!columns.some((c) => c.kind === 'pos') || !columns.some((c) => c.kind === 'neg')) return
  const grid = doc.createElement('div')
  grid.className = 'conseq'
  columns[0].label.before(grid)
  columns.forEach(({ kind, label, list }) => {
    const col = doc.createElement('div')
    col.className = `conseq-col ${kind}`
    col.innerHTML = `<p class="option-label">${escapeHtml(text(label).replace(/:$/, ''))}</p>`
    col.appendChild(list)
    label.remove()
    grid.appendChild(col)
  })
}

const IMPACT_ROW: Record<string, number> = { alto: 0, alta: 0, medio: 1, media: 1, bajo: 2, baja: 2 }
const PROBABILITY_COL: Record<string, number> = { baja: 0, bajo: 0, media: 1, medio: 1, alta: 2, alto: 2 }

// 7.4 Riesgos: numera cada riesgo (R1, R2...) y arma la matriz impacto x
// probabilidad encima de la tabla. Los ADR anteriores, sin columna de
// probabilidad, quedan solo con la tabla.
function riskMatrix(doc: Document, root: Element): void {
  const heading = findHeading(root, 'h5', /^7\.4\s/)
  if (!heading) return
  const table = sectionSiblings(heading)
    .map((el) => (el.tagName === 'TABLE' ? el : el.querySelector('table')))
    .find(Boolean)
  if (!table) return
  const headers = headerCells(table)
  const riskCol = headers.findIndex((h) => h.startsWith('riesgo'))
  const impactCol = headers.findIndex((h) => h.startsWith('impacto'))
  const probabilityCol = headers.findIndex((h) => h.startsWith('probabilidad'))
  if (riskCol < 0 || impactCol < 0 || probabilityCol < 0) return
  const grid: string[][][] = [0, 1, 2].map(() => [[], [], []])
  bodyRows(table).forEach((cells, index) => {
    const id = `R${index + 1}`
    cells[riskCol]?.insertAdjacentHTML('afterbegin', `<span class="risk-id">${id}</span>`)
    const row = IMPACT_ROW[normalize(text(cells[impactCol])).split(/\W/)[0]]
    const col = PROBABILITY_COL[normalize(text(cells[probabilityCol])).split(/\W/)[0]]
    if (row !== undefined && col !== undefined) grid[row][col].push(id)
  })
  if (!grid.flat(2).length) return
  const severity = (row: number, col: number) => {
    const score = 2 - row + col
    return score >= 3 ? 'sev-high' : score === 2 ? 'sev-mid' : 'sev-low'
  }
  const impacts = ['alto', 'medio', 'bajo']
  const matrix = doc.createElement('div')
  matrix.className = 'risk-matrix'
  matrix.innerHTML =
    `<p class="option-label">Matriz de riesgos (impacto × probabilidad)</p>` +
    `<table><thead><tr><th></th><th>Prob. baja</th><th>Prob. media</th><th>Prob. alta</th></tr></thead><tbody>` +
    impacts
      .map(
        (impact, row) =>
          `<tr><th>Impacto ${impact}</th>${grid[row]
            .map((ids, col) => `<td class="${severity(row, col)}">${ids.join(' ')}</td>`)
            .join('')}</tr>`,
      )
      .join('') +
    `</tbody></table>`
  tableBox(table, root).before(matrix)
}

// Notas del agente: lo que escribió la revisión automática (o el aviso de que
// no se pudo redactar la guía) va firmado con el avatar del robot.
function agentNotes(doc: Document, root: Element): void {
  root.querySelectorAll('blockquote').forEach((el) => {
    const content = text(el)
    const review = /^revisi[oó]n autom[aá]tica/i.test(content)
    if (!review && !/^aviso:/i.test(content)) return
    if (review) el.classList.add('warn')
    el.classList.add('agent-note')
    const body = doc.createElement('div')
    body.className = 'agent-note-body'
    body.innerHTML = '<p class="agent-label">Nota del agente</p>'
    while (el.firstChild) body.appendChild(el.firstChild)
    el.innerHTML = `<img class="agent-avatar" src="${robotAvatar}" alt="">`
    el.appendChild(body)
  })
}

/** Documento HTML completo, listo para imprimir o guardar como PDF. */
export function buildAdrPrintDocument(bodyHtml: string, options: AdrPrintOptions): string {
  const parsed = new DOMParser().parseFromString(`<div id="adr-root">${bodyHtml}</div>`, 'text/html')
  const root = parsed.getElementById('adr-root') as HTMLElement
  // Las clases de Tailwind del panel no aplican en la ventana de impresión.
  root.querySelectorAll('[class]').forEach((el) => el.removeAttribute('class'))

  const firstSection = root.querySelector('h4')
  const titleEl = root.querySelector('h3')
  const heading = text(titleEl) || options.title
  const projectTitle = heading.replace(/^ADR-\d+:\s*/i, '')
  const adrNumber = heading.match(/^(ADR-\d+)/i)?.[1] ?? 'ADR'
  titleEl?.remove()

  // Tabla de datos (Estado, Fecha, Proyecto...) e introducción: van a la portada.
  const metaRows: Array<[string, string]> = []
  const metaTable = root.querySelector('table')
  if (metaTable && isBefore(metaTable, firstSection)) {
    metaTable.querySelectorAll('tr').forEach((row) => {
      const cells = row.querySelectorAll('td')
      if (cells.length >= 2) metaRows.push([text(cells[0]), text(cells[1])])
    })
    tableBox(metaTable, root).remove()
  }
  const intro = root.querySelector('blockquote')
  let introHtml = ''
  if (intro && isBefore(intro, firstSection)) {
    introHtml = intro.innerHTML
    intro.remove()
  }

  const status = metaRows.find(([key]) => /^estado$/i.test(key))?.[1] ?? ''
  const coverRows = metaRows.filter(([key]) => !/^(estado|campo)$/i.test(key))

  // Capítulos: ids para la tabla de contenido y saltos de página.
  const toc: Array<{ id: string; label: string; sub: boolean }> = []
  root.querySelectorAll('h4, h5').forEach((el, index) => {
    const label = text(el)
    if (!label) return
    const isChapter = el.tagName === 'H4'
    // En la tabla de contenido solo van las subsecciones numeradas (7.1, 7.2...).
    if (!isChapter && !/^\d+\.\d+\s/.test(label)) return
    const id = `adr-sec-${index + 1}`
    el.id = id
    toc.push({ id, label, sub: !isChapter })
    if (isChapter && PAGE_BREAK_BEFORE.test(label)) {
      el.classList.add('page-break')
      el.insertAdjacentHTML('afterbegin', `<img class="chapter-logo" src="${robotAvatar}" alt="">`)
    }
  })

  // Resumen ejecutivo en un recuadro; de él salen los datos de la portada.
  const facts: Array<{ label: string; value: string; wide?: boolean }> = []
  const exec = Array.from(root.querySelectorAll('h4')).find((el) => /^resumen ejecutivo/i.test(text(el)))
  if (exec) {
    const box = parsed.createElement('div')
    box.className = 'exec'
    let next = exec.nextElementSibling
    while (next && next.tagName !== 'H4') {
      const current = next
      next = next.nextElementSibling
      box.appendChild(current)
    }
    exec.after(box)
    const decided = Array.from(box.querySelectorAll('p'))
      .map((p) => text(p).match(/^qu[eé] se decidi[oó]:\s*(?:construir el sistema como\s+)?(.+?)\.?(?:\s+El diagrama aprobado.*)?$/i)?.[1])
      .find(Boolean)
    if (decided && !/^ver la secci/i.test(decided)) {
      facts.push({ label: 'Decisión', value: decided.replace(/\s*\[\d+\]/g, ''), wide: true })
    }
    box.querySelectorAll('li').forEach((li) => {
      const match = text(li).match(/^(presupuesto|equipo|plazo):\s*(.+)$/i)
      if (match) facts.push({ label: match[1], value: match[2] })
    })
  }

  // Pie de cada diagrama: el párrafo en cursiva que le sigue en el ADR
  // ("Figura 1. ...") pasa a ser su <figcaption>.
  root.querySelectorAll('figure').forEach((figure) => {
    const next = figure.nextElementSibling
    const em = next?.firstElementChild
    if (next?.tagName !== 'P' || next.children.length !== 1 || em?.tagName !== 'EM' || text(next) !== text(em)) return
    const caption = parsed.createElement('figcaption')
    caption.innerHTML = em.innerHTML.replace(/^(Figura \d+\.)/, '<strong>$1</strong>')
    figure.appendChild(caption)
    next.remove()
  })
  const diagramSrc = root.querySelector('figure img')?.getAttribute('src') ?? ''

  tradeoffCards(parsed, root)
  qualityChips(parsed, root)
  consequenceColumns(parsed, root)
  riskMatrix(parsed, root)
  agentNotes(parsed, root)

  // Sin introducción ni decisión en la ficha, la portada lleva la decisión en
  // una línea (del resumen ejecutivo).
  if (!introHtml && !facts.some((f) => f.wide)) {
    const decided = Array.from(root.querySelectorAll('p')).find((p) => /^qu[eé] se decidi[oó]:/i.test(text(p)))
    if (decided) introHtml = `<p>${decided.innerHTML}</p>`
  }

  const factsHtml = facts.length
    ? `<div class="cover-facts">${facts
        .map(
          (f) =>
            `<div class="fact${f.wide ? ' wide' : ''}"><span class="fact-label">${escapeHtml(f.label)}</span>` +
            `<span class="fact-value">${escapeHtml(shorten(f.value, f.wide ? 140 : 90))}</span></div>`,
        )
        .join('')}</div>`
    : ''
  const metaHtml = coverRows.length
    ? `<table class="cover-meta"><tbody>${coverRows
        .map(([key, value]) => `<tr><th>${escapeHtml(key)}</th><td>${escapeHtml(value)}</td></tr>`)
        .join('')}</tbody></table>`
    : ''
  const thumbHtml = diagramSrc
    ? `<figure class="cover-thumb"><img src="${escapeHtml(diagramSrc)}" alt="Vista general de la arquitectura">` +
      `<figcaption>Vista general (detalle en la sección 4)</figcaption></figure>`
    : ''

  const cover =
    `<section class="cover">` +
    `<div class="cover-band">` +
    `<div class="cover-top"><span class="brand"><img class="brand-logo" src="${robotAvatar}" alt="">Arch<span>Agent</span></span>` +
    `<span class="doc-type">Architecture Decision Record</span></div>` +
    `<div class="cover-hero"><div class="cover-main"><p class="eyebrow">${escapeHtml(adrNumber)}</p>` +
    `<h1>${escapeHtml(projectTitle)}</h1>` +
    `<p class="subtitle">Registro de decisión de arquitectura de software</p>` +
    (status ? `<span class="badge${/^aceptado/i.test(status) ? ' ok' : ''}">${escapeHtml(status)}</span>` : '') +
    `</div><div class="cover-robot"><img class="robot-body" src="${robotBody}" alt="">` +
    `<img class="robot-arm" src="${waveArm}" alt=""></div></div></div>` +
    `<div class="cover-body">${factsHtml}` +
    (thumbHtml || metaHtml ? `<div class="cover-row">${thumbHtml}${metaHtml ? `<div>${metaHtml}</div>` : ''}</div>` : '') +
    (introHtml ? `<div class="cover-note">${introHtml}</div>` : '') +
    `</div></section>`

  const tocHtml = toc.length
    ? `<nav class="toc"><h2>Contenido</h2><ol>${toc
        .map((item) => `<li${item.sub ? ' class="sub"' : ''}><a href="#${item.id}">${escapeHtml(item.label)}</a></li>`)
        .join('')}</ol></nav>`
    : ''

  const base = options.baseHref ? `<base href="${escapeHtml(options.baseHref)}/">` : ''
  return (
    `<!doctype html><html lang="es"><head><meta charset="utf-8">${base}` +
    `<link rel="stylesheet" href="${escapeHtml(ADR_FONTS_HREF)}">` +
    `<title>${escapeHtml(options.title)}</title><style>${PRINT_STYLES(projectTitle)}</style></head>` +
    `<body><p class="print-note">Para guardarlo como PDF, elige "Guardar como PDF" en el destino de impresión ` +
    `y desactiva "Encabezados y pies de página" del navegador (el documento ya trae los suyos).</p>` +
    `${cover}${tocHtml}<main>${root.innerHTML}</main></body></html>`
  )
}
