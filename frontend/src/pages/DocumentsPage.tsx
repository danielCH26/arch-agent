import { useEffect, useState, useRef } from 'react'
import { useParams } from 'react-router-dom'
import { getProject, Project } from '../api/projects'
import { Document, listDocuments } from '../api/documents'
import { DocumentUploader } from '../components/DocumentUploader'
import { DocumentList } from '../components/DocumentList'
import { projectsStore } from '../stores/projectsStore'

export function DocumentsPage() {
  const { id } = useParams<{ id: string }>()
  const [project, setProject] = useState<Project | null>(null)
  const [documents, setDocuments] = useState<Document[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const projectId = Number(id)

  const fetchDocuments = async () => {
    if (!projectId || isNaN(projectId)) return

    try {
      const docs = await listDocuments(projectId)
      setDocuments(docs)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error al cargar documentos')
    }
  }

  // Polling: si hay documentos sin procesar, refrescar cada 3s
  useEffect(() => {
    const hasUnprocessed = documents.some((d) => !d.processed)

    if (hasUnprocessed && !pollRef.current) {
      pollRef.current = setInterval(fetchDocuments, 3000)
    } else if (!hasUnprocessed && pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }

    return () => {
      if (pollRef.current) {
        clearInterval(pollRef.current)
        pollRef.current = null
      }
    }
  }, [documents])

  useEffect(() => {
    const loadData = async () => {
      setLoading(true)
      setError('')

      try {
        const projectData = await getProject(projectId)
        setProject(projectData)
        // Setear proyecto activo para que el sidebar lo refleje
        projectsStore.getState().setCurrentProject(projectData)
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Error al cargar proyecto')
      }

      await fetchDocuments()
      setLoading(false)
    }

    loadData()
  }, [id])

  if (loading) {
    return (
      <div className="flex justify-center py-12">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
      </div>
    )
  }

  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-900 mb-6">
        Documentos {project && `- ${project.name}`}
      </h1>

      {error && (
        <div className="mb-4 p-4 bg-red-50 text-red-700 rounded-lg">
          {error}
        </div>
      )}

      <div className="space-y-6">
        <div>
          <h2 className="text-lg font-medium text-gray-900 mb-3">Subir documento</h2>
          <DocumentUploader
            projectId={projectId}
            onUploadComplete={fetchDocuments}
          />
        </div>

        <div>
          <h2 className="text-lg font-medium text-gray-900 mb-3">Documentos existentes</h2>
          <DocumentList documents={documents} onRefresh={fetchDocuments} />
        </div>
      </div>
    </div>
  )
}
