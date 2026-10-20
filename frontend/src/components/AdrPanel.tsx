import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { approveAdr, generateAdr, getAdr, type AdrOut } from '../api/adr'
import { fetchDiagramHistory, type DiagramVersion } from '../api/diagrams'
import { renderMarkdownBlocks } from './MessageBubble'
import { ProjectCompletedDialog } from './ProjectCompletedDialog'
import { buildAdrPrintDocument } from './adrPrint'

interface AdrPanelProps {
  projectId: number
  projectName?: string | null
  // Se llama al aprobar el ADR (proyecto terminado) para refrescar la página.
  onCompleted?: () => void | Promise<void>
}

// Nombre de archivo seguro a partir del nombre del proyecto.
export function adrFilename(projectName?: string | null): string {
  const slug = (projectName ?? '')
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
  return `ADR-${slug || 'proyecto'}.md`
}

function downloadMarkdown(markdown: string, filename: string) {
  const blob = new Blob([markdown], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  // Firefox y Safari pueden cancelar la descarga si la URL se revoca en el
  // mismo tick del click: se libera un momento después.
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

// Parte el ADR en el bloque ```mermaid: en el PDF el diagrama va como imagen
// (la captura aprobada), no como código, que una persona no técnica no puede leer.
export function splitAtMermaid(markdown: string): { before: string; after: string; hasMermaid: boolean } {
  const match = markdown.match(/```mermaid\s*\n[\s\S]*?```/i)
  if (!match || match.index === undefined) return { before: markdown, after: '', hasMermaid: false }
  return {
    before: markdown.slice(0, match.index),
    after: markdown.slice(match.index + match[0].length),
    hasMermaid: true,
  }
}

// Abre una vista del ADR lista para imprimir y lanza el diálogo de impresión,
// donde se elige "Guardar como PDF". Así no hacen falta librerías ni backend.
export function openPrintView(bodyHtml: string, title: string): boolean {
  const win = window.open('', '_blank')
  if (!win) return false
  win.document.open()
  win.document.write(buildAdrPrintDocument(bodyHtml, { title, baseHref: window.location.origin }))
  win.document.close()
  let printed = false
  const print = () => {
    if (printed) return
    printed = true
    win.focus()
    win.print()
  }
  // Se espera a que cargue la imagen del diagrama; si tarda, se imprime igual.
  win.addEventListener('load', print)
  setTimeout(print, 2500)
  return true
}

// El diagrama que usa el ADR (mismo adjunto que su Mermaid). Para ADR viejos,
// sin ese dato, el aprobado más reciente o el último generado.
export function pickAdrDiagram(diagrams: DiagramVersion[], attachmentId?: string | null): DiagramVersion | null {
  if (attachmentId) {
    const exact = diagrams.find((d) => d.id === attachmentId)
    if (exact) return exact
  }
  return diagrams.find((d) => d.decision === 'approve') ?? diagrams[0] ?? null
}

function formatDate(iso: string | null): string {
  if (!iso) return ''
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleString()
}

/**
 * Fase Revisión: el ADR del proyecto. Reúne lo decidido en todas las fases
 * (requerimientos, propuesta con trade-offs, diagrama, decisiones) más una
 * guía práctica para empezar a construir. Se puede regenerar y descargar en
 * Markdown (GitHub/GitLab renderizan el diagrama Mermaid) o en PDF, con el
 * diagrama como imagen, para quien no es técnico.
 */
export function AdrPanel({ projectId, projectName, onCompleted }: AdrPanelProps) {
  const navigate = useNavigate()
  const [adr, setAdr] = useState<AdrOut | null>(null)
  const [showChanges, setShowChanges] = useState(false)
  const [changes, setChanges] = useState('')
  const [approving, setApproving] = useState(false)
  const [celebrate, setCelebrate] = useState(false)
  const [loading, setLoading] = useState(true)
  const [generating, setGenerating] = useState(false)
  const [error, setError] = useState('')
  const [copied, setCopied] = useState(false)
  // Imágenes de los diagramas del proyecto: el ADR trae el diagrama como
  // código Mermaid, que en el panel se vería como texto.
  const [diagrams, setDiagrams] = useState<DiagramVersion[]>([])

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    getAdr(projectId)
      .then((data) => {
        if (!cancelled) setAdr(data)
      })
      .catch(() => {
        // Sin ADR guardado o error de red: se ofrece generarlo.
        if (!cancelled) setAdr(null)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    fetchDiagramHistory(projectId)
      .then((list) => {
        if (!cancelled) setDiagrams(list)
      })
      .catch(() => undefined)
    return () => {
      cancelled = true
    }
  }, [projectId])

  async function handleGenerate(feedback?: string) {
    setGenerating(true)
    setError('')
    try {
      setAdr(await generateAdr(projectId, feedback))
      setShowChanges(false)
      setChanges('')
    } catch (err) {
      setError(err instanceof Error && err.message ? err.message : 'No se pudo generar el ADR.')
    } finally {
      setGenerating(false)
    }
  }

  async function handleApprove() {
    setApproving(true)
    setError('')
    try {
      setAdr(await approveAdr(projectId))
      setCelebrate(true)
      void Promise.resolve(onCompleted?.()).catch(() => undefined)
    } catch (err) {
      setError(err instanceof Error && err.message ? err.message : 'No se pudo aprobar el ADR.')
    } finally {
      setApproving(false)
    }
  }

  async function handleCopy() {
    if (!adr?.markdown) return
    try {
      await navigator.clipboard.writeText(adr.markdown)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      setError('No se pudo copiar al portapapeles.')
    }
  }

  const markdown = adr?.markdown ?? null
  const completed = Boolean(adr?.approved_at)
  const busy = generating || approving || loading
  const diagram = pickAdrDiagram(diagrams, adr?.diagram_attachment_id)
  // Copia del ADR armada para imprimir (oculta): el diagrama va como imagen.
  const printRef = useRef<HTMLDivElement>(null)
  const printParts = markdown ? splitAtMermaid(markdown) : null

  function handleDownloadPdf() {
    const html = printRef.current?.innerHTML ?? ''
    const opened = openPrintView(html, adrFilename(projectName).replace(/\.md$/, ''))
    if (!opened) setError('El navegador bloqueó la ventana. Permite las ventanas emergentes para descargar el PDF.')
  }
  const warnings = adr?.guide_warnings ?? []

  return (
    <section
      data-testid="adr-panel"
      aria-labelledby="adr-panel-title"
      className="rounded-xl border border-indigo-200 bg-white p-4 shadow-sm dark:border-indigo-900 dark:bg-gray-900"
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 id="adr-panel-title" className="text-base font-semibold text-gray-900 dark:text-gray-100">
            Documento de arquitectura (ADR)
          </h2>
          <p className="text-xs text-gray-600 dark:text-gray-400">
            Reúne todo lo decidido en las fases anteriores y una guía para empezar a construir.
            {adr?.generated_at && ` Generado: ${formatDate(adr.generated_at)}.`}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {markdown && (
            <>
              <button
                type="button"
                data-testid="adr-download"
                onClick={() => downloadMarkdown(markdown, adrFilename(projectName))}
                className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700"
              >
                Descargar .md
              </button>
              <button
                type="button"
                data-testid="adr-download-pdf"
                onClick={handleDownloadPdf}
                title="Abre el documento listo para imprimir o guardar como PDF"
                className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700"
              >
                Descargar PDF
              </button>
              <button
                type="button"
                onClick={() => void handleCopy()}
                className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-100 dark:border-gray-600 dark:text-gray-200 dark:hover:bg-gray-800"
              >
                {copied ? 'Copiado' : 'Copiar'}
              </button>
            </>
          )}
          {!completed && (
          <button
            type="button"
            data-testid="adr-generate"
            disabled={busy}
            onClick={() => void handleGenerate()}
            className={
              markdown
                ? 'rounded-lg border border-indigo-300 px-3 py-1.5 text-sm text-indigo-700 hover:bg-indigo-50 disabled:opacity-50 dark:text-indigo-300'
                : 'rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50'
            }
          >
            {generating ? 'Generando…' : markdown ? 'Regenerar ADR' : 'Generar ADR'}
          </button>
          )}
        </div>
      </div>

      {markdown && !completed && (
        <div className="mt-3 flex flex-wrap items-center gap-2 rounded-lg bg-indigo-50 px-3 py-2 dark:bg-indigo-950">
          <p className="mr-auto text-sm text-indigo-900 dark:text-indigo-200">
            Revisa el documento. Si está bien, apruébalo para terminar el proyecto.
          </p>
          <button
            type="button"
            data-testid="adr-request-changes"
            disabled={busy}
            onClick={() => setShowChanges((value) => !value)}
            className="rounded-lg border border-indigo-300 bg-white px-3 py-1.5 text-sm text-indigo-700 hover:bg-indigo-100 disabled:opacity-50"
          >
            Solicitar cambios
          </button>
          <button
            type="button"
            data-testid="adr-approve"
            disabled={busy}
            onClick={() => void handleApprove()}
            className="rounded-lg bg-green-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-50"
          >
            {approving ? 'Aprobando…' : 'Aprobar y finalizar proyecto'}
          </button>
        </div>
      )}

      {showChanges && (
        <div className="mt-3 space-y-2" data-testid="adr-changes-form">
          <label htmlFor={`adr-changes-${projectId}`} className="block text-sm font-medium text-gray-800 dark:text-gray-200">
            ¿Qué quieres cambiar en el ADR?
          </label>
          {completed && (
            <p className="text-xs text-amber-800" data-testid="adr-reopen-note">
              El ADR ya está aprobado: al aplicar los cambios el proyecto se reabre y tendrás que aprobarlo otra vez.
            </p>
          )}
          <textarea
            id={`adr-changes-${projectId}`}
            value={changes}
            onChange={(event) => setChanges(event.target.value)}
            rows={3}
            maxLength={2000}
            placeholder="Por ejemplo: usar Redis para caché, agregar un riesgo sobre la integración con la EPS…"
            className="w-full rounded-lg border border-gray-300 p-2 text-sm text-gray-900 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100"
          />
          <button
            type="button"
            data-testid="adr-send-changes"
            disabled={busy || !changes.trim()}
            onClick={() => void handleGenerate(changes.trim())}
            className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
          >
            Aplicar cambios y regenerar
          </button>
        </div>
      )}

      {completed && (
        <div
          role="status"
          data-testid="adr-completed"
          className="mt-3 flex flex-wrap items-center gap-2 rounded-lg bg-green-50 px-3 py-2 text-sm text-green-800"
        >
          <span className="mr-auto font-medium">✅ Proyecto completado. El ADR quedó aprobado.</span>
          <button
            type="button"
            data-testid="adr-reopen"
            disabled={busy}
            onClick={() => setShowChanges((value) => !value)}
            className="rounded-lg border border-green-300 px-3 py-1.5 hover:bg-green-100 disabled:opacity-50"
          >
            Pedir cambios (reabre el proyecto)
          </button>
          <button
            type="button"
            onClick={() => navigate('/projects', { state: { openCreate: true } })}
            className="rounded-lg bg-green-600 px-3 py-1.5 text-white hover:bg-green-700"
          >
            Crear otro proyecto
          </button>
          <button
            type="button"
            onClick={() => navigate('/projects')}
            className="rounded-lg border border-green-300 px-3 py-1.5 hover:bg-green-100"
          >
            Ir al inicio
          </button>
        </div>
      )}

      {generating && (
        <p role="status" className="mt-3 text-sm text-indigo-800 dark:text-indigo-300">
          Generando el ADR con las decisiones del proyecto. Puede tardar hasta un minuto…
        </p>
      )}

      {error && (
        <div role="alert" data-testid="adr-error" className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </div>
      )}

      {!loading && !markdown && !generating && !error && (
        <p className="mt-3 text-sm text-gray-600 dark:text-gray-400" data-testid="adr-empty">
          Todavía no hay un ADR. Genéralo cuando la propuesta y el diagrama estén aprobados.
        </p>
      )}

      {markdown && adr && !adr.guide_complete && (
        <p className="mt-3 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800" data-testid="adr-guide-incomplete">
          La guía práctica (sección 7) no se pudo redactar con el modelo. El resto del documento está completo;
          puedes regenerarlo para intentarlo de nuevo.
        </p>
      )}

      {markdown && warnings.length > 0 && (
        <div className="mt-3 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-900" data-testid="adr-guide-warnings">
          <p className="font-medium">Revisión automática: puntos que no salen de lo decidido o que no cuadran con el resto del documento.</p>
          <ul className="mt-1 list-disc pl-5">
            {warnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        </div>
      )}

      {markdown && diagram && (
        <figure className="mt-3 rounded-lg border border-gray-100 p-3 dark:border-gray-800" data-testid="adr-diagram">
          <figcaption className="mb-2 text-xs font-semibold text-gray-700 dark:text-gray-300">
            {diagram.decision === 'approve' ? 'Diagrama aprobado' : 'Último diagrama generado'}
          </figcaption>
          <img
            src={diagram.url}
            alt="Diagrama de la arquitectura del proyecto"
            className="h-auto max-h-[60vh] w-full max-w-3xl rounded object-contain"
          />
        </figure>
      )}

      {markdown && (
        <article
          data-testid="adr-content"
          className="prose-sm mt-3 max-h-[70vh] overflow-y-auto rounded-lg border border-gray-100 p-3 text-sm text-gray-800 dark:border-gray-800 dark:text-gray-200"
        >
          {renderMarkdownBlocks(markdown)}
        </article>
      )}

      {printParts && (
        <div ref={printRef} hidden data-testid="adr-print-source">
          {renderMarkdownBlocks(printParts.before)}
          {printParts.hasMermaid && diagram && (
            <figure>
              <img src={diagram.url} alt="Diagrama de arquitectura del documento" />
              <figcaption>{diagram.decision === 'approve' ? 'Diagrama aprobado' : 'Último diagrama generado'}</figcaption>
            </figure>
          )}
          {printParts.hasMermaid && !diagram && (
            <p>
              <em>El diagrama está en la versión Markdown del documento.</em>
            </p>
          )}
          {renderMarkdownBlocks(printParts.after)}
        </div>
      )}

      <ProjectCompletedDialog open={celebrate} projectName={projectName} onClose={() => setCelebrate(false)} />
    </section>
  )
}
