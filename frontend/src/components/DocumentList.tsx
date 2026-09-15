import { useState } from 'react'
import { Document, deleteDocument } from '../api/documents'

interface DocumentListProps {
  documents: Document[]
  onRefresh: () => void
}

export function DocumentList({ documents, onRefresh }: DocumentListProps) {
  const [deletingId, setDeletingId] = useState<number | null>(null)
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [bulkDeleting, setBulkDeleting] = useState(false)
  const [error, setError] = useState('')

  const toggleSelected = (docId: number) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(docId)) {
        next.delete(docId)
      } else {
        next.add(docId)
      }
      return next
    })
  }

  const toggleSelectAll = () => {
    setSelected((prev) => (prev.size === documents.length ? new Set() : new Set(documents.map((d) => d.id))))
  }

  const handleDelete = async (docId: number) => {
    setDeletingId(docId)
    setError('')

    try {
      await deleteDocument(docId)
      setSelected((prev) => {
        const next = new Set(prev)
        next.delete(docId)
        return next
      })
      onRefresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error al eliminar documento')
    } finally {
      setDeletingId(null)
    }
  }

  const handleDeleteSelected = async () => {
    setBulkDeleting(true)
    setError('')
    try {
      await Promise.all(Array.from(selected).map((id) => deleteDocument(id)))
      setSelected(new Set())
      onRefresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error al eliminar documentos')
    } finally {
      setBulkDeleting(false)
    }
  }

  const formatSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  }

  const getFileIcon = (fileType: string) => {
    if (fileType === 'pdf') {
      return (
        <svg className="w-5 h-5 shrink-0 text-red-500" fill="currentColor" viewBox="0 0 24 24">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6zm-1 2l5 5h-5V4zM8.5 13c-.55 0-1 .45-1 1v4c0 .55.45 1 1 1s1-.45 1-1v-4c0-.55-.45-1-1-1zm4 0c-.55 0-1 .45-1 1v4c0 .55.45 1 1 1s1-.45 1-1v-4c0-.55-.45-1-1-1zm3 3.5c-.28 0-.5.22-.5.5s.22.5.5.5.5-.22.5-.5-.22-.5-.5-.5z"/>
        </svg>
      )
    }
    return (
      <svg className="w-5 h-5 shrink-0 text-blue-500" fill="currentColor" viewBox="0 0 24 24">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6zm-1 2l5 5h-5V4zM8 12h8v2H8v-2zm0 3h8v2H8v-2z"/>
      </svg>
    )
  }

  if (documents.length === 0) {
    return (
      <div className="text-center py-8 text-gray-500">
        <svg className="mx-auto h-10 w-10 text-gray-300 mb-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
        </svg>
        <p>No hay documentos</p>
      </div>
    )
  }

  return (
    <div>
      {error && (
        <div className="mb-4 p-3 bg-red-50 text-red-700 rounded-lg text-sm">
          {error}
        </div>
      )}

      <div className="overflow-x-auto rounded-[10px] border border-gray-200">
        <table className="w-full text-left">
          <thead>
            <tr className="border-b border-gray-200 bg-gray-50 text-sm text-gray-700">
              <th className="w-10 px-3 py-2">
                <input
                  type="checkbox"
                  checked={selected.size === documents.length && documents.length > 0}
                  onChange={toggleSelectAll}
                  aria-label="Seleccionar todos"
                />
              </th>
              <th className="px-3 py-2 font-medium">Nombre del documento</th>
              <th className="px-3 py-2 font-medium">Tamaño</th>
              <th className="px-3 py-2 font-medium">Estado</th>
              <th className="w-10 px-3 py-2" />
            </tr>
          </thead>
          <tbody>
            {documents.map((doc) => (
              <tr key={doc.id} className="border-b border-gray-100 last:border-0 hover:bg-gray-50">
                <td className="px-3 py-2">
                  <input
                    type="checkbox"
                    checked={selected.has(doc.id)}
                    onChange={() => toggleSelected(doc.id)}
                    aria-label={`Seleccionar ${doc.filename}`}
                  />
                </td>
                <td className="px-3 py-2">
                  <div className="flex items-center gap-2 min-w-0">
                    {getFileIcon(doc.file_type)}
                    <span className="font-medium text-gray-900 truncate">{doc.filename}</span>
                    {doc.version > 1 && (
                      <span className="px-1.5 py-0.5 bg-gray-100 text-gray-600 text-xs rounded shrink-0">
                        v{doc.version}
                      </span>
                    )}
                  </div>
                </td>
                <td className="px-3 py-2 text-sm text-gray-700">{formatSize(doc.file_size_bytes)}</td>
                <td className="px-3 py-2 text-sm">
                  {doc.processed ? (
                    <span className="inline-flex items-center gap-1 text-green-700">
                      <span aria-hidden="true">✅</span> Subido
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 text-amber-700">
                      <span className="animate-spin inline-block h-3 w-3 border-b border-amber-600 rounded-full"></span>
                      Procesando...
                    </span>
                  )}
                </td>
                <td className="px-3 py-2">
                  <button
                    onClick={() => handleDelete(doc.id)}
                    disabled={deletingId === doc.id}
                    className="p-1 text-gray-400 hover:text-red-600 transition-colors disabled:opacity-50"
                    title="Eliminar documento"
                  >
                    {deletingId === doc.id ? (
                      <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-red-600"></div>
                    ) : (
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                      </svg>
                    )}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {selected.size > 0 && (
        <div className="mt-3 flex justify-end">
          <button
            onClick={handleDeleteSelected}
            disabled={bulkDeleting}
            className="rounded-lg border border-gray-300 px-4 py-1.5 text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-50"
          >
            {bulkDeleting ? 'Eliminando...' : `Eliminar seleccionados (${selected.size})`}
          </button>
        </div>
      )}
    </div>
  )
}
