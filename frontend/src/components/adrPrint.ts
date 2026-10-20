// Versión imprimible del ADR (lo que se guarda como PDF).
//
// El ADR es el entregable del proyecto: lo que se le pasa a la empresa o al
// cliente. Antes el PDF era el markdown impreso tal cual; ahora se arma como
// un documento técnico: portada con el estado y los datos del proyecto, tabla
// de contenido, resumen ejecutivo destacado, cada capítulo grande en su propia
// página, encabezado y pie con número de página, y tablas legibles.
//
// Todo se hace sobre el HTML que ya renderiza el panel (mismo contenido que el
// .md), sin librerías ni backend.

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

const PRINT_STYLES = (runningTitle: string) => `
  @page {
    size: A4;
    margin: 22mm 18mm 20mm;
    @top-left { content: ${cssString(runningTitle)}; font: 8pt 'Segoe UI', Helvetica, Arial, sans-serif; color: #6b7280; }
    @top-right { content: "Documento de decisión de arquitectura"; font: 8pt 'Segoe UI', Helvetica, Arial, sans-serif; color: #6b7280; }
    @bottom-left { content: "Generado con ArchAgent"; font: 8pt 'Segoe UI', Helvetica, Arial, sans-serif; color: #9ca3af; }
    @bottom-right { content: "Página " counter(page) " de " counter(pages); font: 8pt 'Segoe UI', Helvetica, Arial, sans-serif; color: #6b7280; }
  }
  @page :first {
    @top-left { content: none; } @top-right { content: none; }
    @bottom-left { content: none; } @bottom-right { content: none; }
  }
  * { box-sizing: border-box; }
  html { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  body { font-family: 'Segoe UI', 'Helvetica Neue', Helvetica, Arial, sans-serif; color: #1f2937; line-height: 1.55; font-size: 10.5pt; margin: 0; }
  @media screen { body { max-width: 210mm; margin: 0 auto; padding: 16mm 18mm; background: #fff; } html { background: #e5e7eb; } }

  .print-note { font-size: 9pt; color: #4338ca; background: #eef2ff; border: 1px solid #c7d2fe; border-radius: 6px; padding: 6pt 10pt; margin-bottom: 14pt; }
  @media print { .print-note { display: none; } }

  /* Portada */
  .cover { min-height: 250mm; display: flex; flex-direction: column; justify-content: space-between; break-after: page; }
  .cover-top { display: flex; justify-content: space-between; align-items: center; border-bottom: 3px solid #3730a3; padding-bottom: 8pt; }
  .brand { font-weight: 700; font-size: 13pt; color: #3730a3; letter-spacing: .02em; }
  .doc-type { font-size: 9pt; color: #6b7280; text-transform: uppercase; letter-spacing: .08em; }
  .cover-main { margin-top: 55mm; }
  .eyebrow { font-size: 10pt; font-weight: 600; color: #4f46e5; text-transform: uppercase; letter-spacing: .12em; margin: 0 0 6pt; }
  .cover h1 { font-size: 30pt; line-height: 1.15; color: #111827; margin: 0 0 10pt; }
  .subtitle { font-size: 13pt; color: #4b5563; margin: 0 0 18pt; }
  .badge { display: inline-block; font-size: 10pt; font-weight: 600; padding: 4pt 12pt; border-radius: 999px; background: #fef3c7; color: #92400e; border: 1px solid #fcd34d; }
  .badge.ok { background: #dcfce7; color: #166534; border-color: #86efac; }
  .cover-meta { width: 100%; border-collapse: collapse; font-size: 9.5pt; margin-top: 18mm; }
  .cover-meta th { width: 32%; text-align: left; font-weight: 600; color: #374151; background: transparent; border: 0; border-bottom: 1px solid #e5e7eb; padding: 5pt 0; }
  .cover-meta td { border: 0; border-bottom: 1px solid #e5e7eb; padding: 5pt 0; color: #111827; background: transparent !important; }
  .cover-note { font-size: 9pt; color: #4b5563; border-top: 1px solid #e5e7eb; padding-top: 8pt; margin-top: 10mm; }
  .cover-note p { margin: 0; }

  /* Contenido */
  .toc { break-after: page; }
  .toc h2 { font-size: 18pt; color: #111827; margin: 0 0 12pt; border-bottom: 3px solid #3730a3; padding-bottom: 6pt; }
  .toc ol { list-style: none; padding: 0; margin: 0; }
  .toc li { border-bottom: 1px dotted #d1d5db; padding: 5pt 0; font-size: 11pt; }
  .toc li.sub { padding-left: 16pt; font-size: 9.5pt; color: #4b5563; border-bottom: 0; padding-top: 2pt; padding-bottom: 2pt; }
  .toc a { color: inherit; text-decoration: none; }

  h3, h4, h5, h6 { color: #111827; line-height: 1.25; break-after: avoid; }
  h4 { font-size: 16pt; margin: 22pt 0 10pt; padding: 0 0 5pt; border-bottom: 2px solid #c7d2fe; color: #1e1b4b; }
  h4.page-break { break-before: page; margin-top: 0; }
  h5 { font-size: 12pt; margin: 16pt 0 6pt; color: #3730a3; }
  h6 { font-size: 10.5pt; margin: 12pt 0 4pt; color: #374151; }
  p, ul, ol { margin: 0 0 8pt; }
  li { margin-bottom: 2pt; }
  strong { color: #111827; }

  table { border-collapse: collapse; width: 100%; margin: 6pt 0 12pt; font-size: 9pt; }
  thead { display: table-header-group; }
  tr { break-inside: avoid; }
  th, td { border: 1px solid #e5e7eb; padding: 5pt 7pt; text-align: left; vertical-align: top; }
  th { background: #eef2ff; color: #312e81; font-weight: 600; }
  tbody tr:nth-child(even) td { background: #f9fafb; }

  pre, code { font-family: Consolas, 'Courier New', monospace; font-size: 8.5pt; }
  pre { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 4px; padding: 8pt; white-space: pre-wrap; break-inside: avoid; }
  blockquote { margin: 0 0 10pt; padding: 6pt 12pt; border-left: 4px solid #6366f1; background: #eef2ff; border-radius: 0 4px 4px 0; }
  blockquote.warn { border-left-color: #f59e0b; background: #fffbeb; }
  blockquote p:last-child { margin-bottom: 0; }

  .exec { background: #f8fafc; border: 1px solid #e2e8f0; border-left: 5px solid #3730a3; border-radius: 4px; padding: 10pt 14pt; margin-bottom: 8pt; }
  .exec p { margin-bottom: 6pt; }

  img { max-width: 100%; height: auto; }
  figure { margin: 8pt 0 12pt; text-align: center; break-inside: avoid; border: 1px solid #e5e7eb; border-radius: 6px; padding: 10pt; }
  figcaption { font-size: 8.5pt; color: #6b7280; margin-top: 6pt; }
  a { color: #4338ca; }
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

  // Avisos de la revisión automática: recuadro ámbar.
  root.querySelectorAll('blockquote').forEach((el) => {
    if (/^revisi[oó]n autom[aá]tica/i.test(text(el))) el.classList.add('warn')
  })

  const cover =
    `<section class="cover">` +
    `<div class="cover-top"><span class="brand">ArchAgent</span><span class="doc-type">Documento de decisión de arquitectura</span></div>` +
    `<div class="cover-main"><p class="eyebrow">${escapeHtml(adrNumber)}</p>` +
    `<h1>${escapeHtml(projectTitle)}</h1>` +
    `<p class="subtitle">Propuesta de arquitectura de software</p>` +
    (status ? `<span class="badge${/^aceptado/i.test(status) ? ' ok' : ''}">${escapeHtml(status)}</span>` : '') +
    `</div>` +
    `<div>` +
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
    `<title>${escapeHtml(options.title)}</title><style>${PRINT_STYLES(projectTitle)}</style></head>` +
    `<body><p class="print-note">Para guardarlo como PDF, elige "Guardar como PDF" en el destino de impresión ` +
    `y desactiva "Encabezados y pies de página" del navegador (el documento ya trae los suyos).</p>` +
    `${cover}${tocHtml}<main>${root.innerHTML}</main></body></html>`
  )
}
