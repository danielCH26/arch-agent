import { useCallback, useEffect, useRef, useState } from 'react'
import { type Document, listDocuments } from '../api/documents'
import { DocumentUploader } from './DocumentUploader'

// Documentos del proyecto en la fase de Requerimientos.
//
// Antes, en la elicitación no había forma de subir actas, especificaciones o
// notas (el clip estaba desactivado y la página de documentos quedaba
// escondida en el menú). El backend ya los usaba desde la primera pregunta
// (solo lo relevante, ver elicitation_agent._documents_section), pero nadie
// sabía que podía subirlos. Aquí se suben antes de empezar y se ve cuándo
// terminan de procesarse: un documento que todavía se está procesando no
// llega al agente.

interface ElicitationDocumentsProps {
  projectId: number
  /** Antes de empezar: caja grande con arrastrar y soltar. Después: una línea. */
  compact: boolean
  /** Avisa si hay documentos procesándose (para no empezar sin ellos). */
  onProcessingChange?: (processing: boolean) => void
  /** Cambia para pedir que se vuelva a leer la lista (p. ej. tras adjuntar con el clip). */
  refreshKey?: number
}

const POLL_MS = 3000

export function ElicitationDocuments({ projectId, compact, onProcessingChange, refreshKey }: ElicitationDocumentsProps) {
  const [documents, setDocuments] = useState<Document[]>([])
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const refresh = useCallback(async () => {
    try {
      setDocuments(await listDocuments(projectId))
    } catch {
      // Sin documentos o sin conexión: la elicitación sigue igual.
    }
  }, [projectId])

  useEffect(() => {
    void refresh()
  }, [refresh, refreshKey])

  const processing = documents.some((doc) => !doc.processed)

  useEffect(() => {
    onProcessingChange?.(processing)
    if (processing && !pollRef.current) {
      pollRef.current = setInterval(() => void refresh(), POLL_MS)
    } else if (!processing && pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
  }, [processing, refresh, onProcessingChange])

  useEffect(
    () => () => {
      if (pollRef.current) clearInterval(pollRef.current)
    },
    [],
  )

  const list = documents.length > 0 && (
    <ul className="mt-2 space-y-1 text-sm" data-testid="elicitation-documents-list">
      {documents.map((doc) => (
        <li key={doc.id} className="flex items-center gap-2">
          <span aria-hidden="true">📄</span>
          <span className="truncate">{doc.filename}</span>
          <span className={doc.processed ? 'text-green-700' : 'text-amber-700'}>
            {doc.processed ? '· listo' : '· procesando…'}
          </span>
        </li>
      ))}
    </ul>
  )

  if (compact) {
    if (documents.length === 0) return null
    return (
      <div className="rounded-lg bg-gray-50 px-3 py-2 text-xs text-gray-700" data-testid="elicitation-documents">
        <span className="font-medium">Documentos que el agente tiene en cuenta:</span>
        {list}
        <p className="mt-1 text-gray-500">Puedes adjuntar más con el clip; se usan desde la siguiente pregunta.</p>
      </div>
    )
  }

  return (
    <section
      className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm"
      data-testid="elicitation-documents"
      aria-labelledby={`elicitation-docs-${projectId}`}
    >
      <h3 id={`elicitation-docs-${projectId}`} className="text-sm font-semibold text-gray-900">
        ¿Tienes documentos del proyecto? (opcional)
      </h3>
      <p className="mt-1 text-sm text-gray-600">
        Actas de reunión, especificaciones o notas en PDF o Markdown. El agente los lee desde la primera pregunta, usa
        solo lo que sea relevante para el proyecto y no te vuelve a preguntar lo que ya dicen.
      </p>
      <div className="mt-3">
        <DocumentUploader projectId={projectId} onUploadComplete={() => void refresh()} />
      </div>
      {list}
      {processing && (
        <p className="mt-2 text-sm text-amber-800" role="status">
          Procesando documentos… La elicitación empieza cuando terminen, para que el agente los tenga en cuenta.
        </p>
      )}
    </section>
  )
}
