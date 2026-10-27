// Versión imprimible del ADR (lo que se guarda como PDF).
//
// El ADR es el entregable del proyecto: lo que se le pasa a la empresa o al
// cliente. Antes el PDF era el markdown impreso tal cual; ahora se arma como
// un documento técnico: portada con el estado y los datos del proyecto, tabla
// de contenido, resumen ejecutivo destacado, cada capítulo grande en su propia
// página, encabezado y pie con número de página, y tablas legibles.
//
// Todo se hace sobre el HTML que ya renderiza el panel (mismo contenido que el
// .md), sin librerías ni backend. Colores y tipografías salen de adrTheme.ts.

import { ADR_FONTS, ADR_FONTS_HREF, ADR_PALETTE, ADR_SPACE, ADR_TYPE } from './adrTheme'

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
// marca, neutros para el texto, verde/ámbar solo para estados.
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

  /* Portada: banda azul marino a sangre, título grande y ficha del documento */
  .cover { min-height: 297mm; display: flex; flex-direction: column; break-after: page; background: #fff; }
  @media screen { .cover { min-height: 250mm; margin: 0 -18mm 16mm; } }
  .cover-band { background: ${C.navy}; color: #fff; padding: 22mm 20mm 26mm; position: relative; }
  .cover-band::after { content: ""; position: absolute; left: 20mm; bottom: 0; width: 46mm; height: 5pt; background: ${C.accent}; }
  .cover-top { display: flex; justify-content: space-between; align-items: center; margin-bottom: 30mm; }
  .brand { font-family: ${F.heading}; font-weight: 800; font-size: 14pt; letter-spacing: .02em; color: #fff; }
  .brand span { color: ${C.accent}; }
  .doc-type { font-size: 8.5pt; color: ${C.sky}; text-transform: uppercase; letter-spacing: .14em; }
  .eyebrow { font-family: ${F.heading}; font-size: 10pt; font-weight: 700; color: ${C.accent}; text-transform: uppercase; letter-spacing: .16em; margin: 0 0 ${S.sm}pt; }
  .cover h1 { font-family: ${F.heading}; font-size: ${T.cover}pt; font-weight: 800; line-height: 1.12; color: #fff; margin: 0 0 ${S.md}pt; }
  .subtitle { font-size: 12.5pt; color: ${C.sky}; margin: 0 0 ${S.lg}pt; }
  .badge { display: inline-block; font-size: 9.5pt; font-weight: 600; padding: 4pt 12pt; border-radius: 999px; background: ${C.warning_bg}; color: ${C.warning}; }
  .badge.ok { background: ${C.success_bg}; color: ${C.success}; }
  .cover-body { padding: 16mm 20mm 18mm; display: flex; flex-direction: column; flex: 1; justify-content: space-between; }
  .cover-meta { width: 100%; border-collapse: collapse; font-size: 9.5pt; margin: 0; }
  .cover-meta th { width: 34%; text-align: left; font-weight: 600; color: ${C.primary}; background: transparent; border: 0; border-bottom: 1px solid ${C.line}; padding: 6pt 0; }
  .cover-meta td { border: 0; border-bottom: 1px solid ${C.line}; padding: 6pt 0; color: ${C.ink}; background: transparent !important; }
  .cover-note { font-size: 9pt; color: ${C.muted}; border-left: 3px solid ${C.secondary}; padding: 2pt 0 2pt 10pt; margin-top: 10mm; }
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
  tr { break-inside: avoid; }
  th, td { padding: 6pt 8pt; text-align: left; vertical-align: top; border-bottom: 1px solid ${C.line}; }
  th { background: ${C.navy}; color: #fff; font-weight: 600; font-family: ${F.heading}; letter-spacing: .01em; }
  tbody tr:nth-child(even) td { background: ${C.paper}; }
  tbody tr:last-child td { border-bottom: 0; }

  pre, code { font-family: ${F.mono}; font-size: 8.5pt; }
  code { background: ${C.tint}; color: ${C.primary}; padding: 0 3pt; border-radius: 3px; }
  pre { background: ${C.paper}; border: 1px solid ${C.line}; border-left: 3px solid ${C.secondary}; border-radius: 4px; padding: ${S.sm}pt 10pt; white-space: pre-wrap; break-inside: avoid; }
  pre code { background: transparent; color: ${C.ink}; padding: 0; }
  blockquote { margin: 0 0 10pt; padding: ${S.sm}pt ${S.md}pt; border-left: 4px solid ${C.secondary}; background: ${C.tint}; border-radius: 0 4px 4px 0; }
  blockquote.warn { border-left-color: ${C.warning}; background: ${C.warning_bg}; }
  blockquote p:last-child { margin-bottom: 0; }

  .exec { background: ${C.tint}; border: 1px solid ${C.sky}; border-top: 4px solid ${C.primary}; border-radius: 6px; padding: ${S.md}pt 16pt; margin-bottom: ${S.sm}pt; }
  .exec p { margin-bottom: 6pt; }

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
    // La tabla viene envuelta en un <div> con scroll horizontal: se quita entero.
    const wrapper = metaTable.parentElement
    ;(wrapper && wrapper !== root && wrapper.children.length === 1 ? wrapper : metaTable).remove()
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
    if (isChapter && PAGE_BREAK_BEFORE.test(label)) el.classList.add('page-break')
  })

  // Resumen ejecutivo en un recuadro.
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

  // Avisos de la revisión automática: recuadro ámbar.
  root.querySelectorAll('blockquote').forEach((el) => {
    if (/^revisi[oó]n autom[aá]tica/i.test(text(el))) el.classList.add('warn')
  })

  // Sin introducción, la portada lleva la decisión en una línea (del resumen
  // ejecutivo): es lo primero que quiere saber quien recibe el documento.
  if (!introHtml) {
    const decided = Array.from(root.querySelectorAll('p')).find((p) => /^qu[eé] se decidi[oó]:/i.test(text(p)))
    if (decided) introHtml = `<p>${decided.innerHTML}</p>`
  }

  const cover =
    `<section class="cover">` +
    `<div class="cover-band">` +
    `<div class="cover-top"><span class="brand">Arch<span>Agent</span></span><span class="doc-type">Architecture Decision Record</span></div>` +
    `<div class="cover-main"><p class="eyebrow">${escapeHtml(adrNumber)}</p>` +
    `<h1>${escapeHtml(projectTitle)}</h1>` +
    `<p class="subtitle">Registro de decisión de arquitectura de software</p>` +
    (status ? `<span class="badge${/^aceptado/i.test(status) ? ' ok' : ''}">${escapeHtml(status)}</span>` : '') +
    `</div></div>` +
    `<div class="cover-body">` +
    (coverRows.length
      ? `<table class="cover-meta"><tbody>${coverRows
          .map(([key, value]) => `<tr><th>${escapeHtml(key)}</th><td>${escapeHtml(value)}</td></tr>`)
          .join('')}</tbody></table>`
      : '') +
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
