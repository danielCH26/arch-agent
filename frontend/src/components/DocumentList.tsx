import { useState } from 'react'
import { Document, deleteDocument } from '../api/documents'

interface DocumentListProps {
  documents: Document[]
  onRefresh: () => void
}

export function DocumentList({ documents, onRefresh }: DocumentListProps) {
  const [deletingId, setDeletingId] = useState<number | null>(null)
  const [error, setError] = useState('')

  const handleDelete = async (docId: number) => {
    setDeletingId(docId)
    setError('')

    try {
      await deleteDocument(docId)
      onRefresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error al eliminar documento')
    } finally {
      setDeletingId(null)
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
        <svg className="w-8 h-8 text-red-500" fill="currentColor" viewBox="0 0 24 24">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6zm-1 2l5 5h-5V4zM8.5 13c-.55 0-1 .45-1 1v4c0 .55.45 1 1 1s1-.45 1-1v-4c0-.55-.45-1-1-1zm4 0c-.55 0-1 .45-1 1v4c0 .55.45 1 1 1s1-.45 1-1v-4c0-.55-.45-1-1-1zm3 3.5c-.28 0-.5.22-.5.5s.22.5.5.5.5-.22.5-.5-.22-.5-.5-.5z"/>
        </svg>
      )
    }
    return (
      <svg className="w-8 h-8 text-blue-500" fill="currentColor" viewBox="0 0 24 24">
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

      <div className="space-y-2">
        {documents.map((doc) => (
          <div
            key={doc.id}
            className="flex items-center gap-3 p-3 bg-white border border-gray-200 rounded-lg hover:shadow-sm transition-shadow"
          >
            {getFileIcon(doc.file_type)}

            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className="font-medium text-gray-900 truncate">
                  {doc.filename}
                </span>
                {doc.version > 1 && (
                  <span className="px-1.5 py-0.5 bg-gray-100 text-gray-600 text-xs rounded">
                    v{doc.version}
                  </span>
                )}
                <span className={`px-1.5 py-0.5 text-xs rounded uppercase ${
                  doc.file_type === 'pdf' ? 'bg-red-100 text-red-700' : 'bg-blue-100 text-blue-700'
                }`}>
                  {doc.file_type}
                </span>
                {!doc.processed && (
                  <span className="px-1.5 py-0.5 bg-amber-100 text-amber-700 text-xs rounded inline-flex items-center gap-1">
                    <span className="animate-spin inline-block h-3 w-3 border-b border-amber-600 rounded-full"></span>
                    Procesando...
                  </span>
                )}
              </div>
              <div className="text-xs text-gray-500 mt-0.5">
                {formatSize(doc.file_size_bytes)} • {doc.chunk_count} chunks
              </div>
            </div>

            <button
              onClick={() => handleDelete(doc.id)}
              disabled={deletingId === doc.id}
              className="p-2 text-gray-400 hover:text-red-600 transition-colors disabled:opacity-50"
              title="Eliminar documento"
            >
              {deletingId === doc.id ? (
                <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-red-600"></div>
              ) : (
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                </svg>
              )}
            </button>
          </div>
        ))}
      </div>
    </div>
  )
}
