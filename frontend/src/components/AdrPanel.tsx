import { useEffect, useState } from 'react'
import { generateAdr, getAdr, type AdrOut } from '../api/adr'
import { fetchDiagramHistory, type DiagramVersion } from '../api/diagrams'
import { renderMarkdownBlocks } from './MessageBubble'

interface AdrPanelProps {
  projectId: number
  projectName?: string | null
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
  URL.revokeObjectURL(url)
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
 * Markdown (GitHub/GitLab renderizan el diagrama Mermaid).
 */
export function AdrPanel({ projectId, projectName }: AdrPanelProps) {
  const [adr, setAdr] = useState<AdrOut | null>(null)
  const [loading, setLoading] = useState(true)
  const [generating, setGenerating] = useState(false)
  const [error, setError] = useState('')
  const [copied, setCopied] = useState(false)
  // Imagen del diagrama aprobado (o el último): el ADR lo trae como código
  // Mermaid, que en el panel se vería como texto.
  const [diagram, setDiagram] = useState<DiagramVersion | null>(null)

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
      .then((diagrams) => {
        if (!cancelled) setDiagram(diagrams.find((d) => d.decision === 'approve') ?? diagrams[0] ?? null)
      })
      .catch(() => undefined)
    return () => {
      cancelled = true
    }
  }, [projectId])

  async function handleGenerate() {
    setGenerating(true)
    setError('')
    try {
      setAdr(await generateAdr(projectId))
    } catch (err) {
      setError(err instanceof Error && err.message ? err.message : 'No se pudo generar el ADR.')
    } finally {
      setGenerating(false)
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
                onClick={() => void handleCopy()}
                className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-100 dark:border-gray-600 dark:text-gray-200 dark:hover:bg-gray-800"
              >
                {copied ? 'Copiado' : 'Copiar'}
              </button>
            </>
          )}
          <button
            type="button"
            data-testid="adr-generate"
            disabled={generating || loading}
            onClick={() => void handleGenerate()}
            className={
              markdown
                ? 'rounded-lg border border-indigo-300 px-3 py-1.5 text-sm text-indigo-700 hover:bg-indigo-50 disabled:opacity-50 dark:text-indigo-300'
                : 'rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50'
            }
          >
            {generating ? 'Generando…' : markdown ? 'Regenerar ADR' : 'Generar ADR'}
          </button>
        </div>
      </div>

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
    </section>
  )
}
