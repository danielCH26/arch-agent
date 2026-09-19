import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { ApiError } from '../api/client'
import { getProject, Project } from '../api/projects'
import { projectsStore } from '../stores/projectsStore'

export function ProjectPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [project, setProject] = useState<Project | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    const projectId = Number(id)
    if (!projectId || isNaN(projectId)) {
      setError('ID de proyecto inválido')
      setLoading(false)
      return
    }

    getProject(projectId)
      .then((data) => {
        setProject(data)
        // Setear el proyecto activo en el store para que el sidebar muestre
        // Chat / Documentos / Configuración.
        projectsStore.getState().setCurrentProject(data)
        navigate(`/projects/${projectId}/chat`, { replace: true })
      })
      .catch((err) => {
        if (err instanceof ApiError && (err.status === 403 || err.status === 404)) {
          projectsStore.getState().setCurrentProject(null)
          navigate('/projects', {
            replace: true,
            state: { message: 'Ese proyecto ya no está disponible para tu usuario.' },
          })
          return
        }
        setError(err instanceof Error ? err.message : 'Error al cargar el proyecto')
      })
      .finally(() => {
        setLoading(false)
      })
  }, [id, navigate])

  if (loading) {
    return (
      <div className="flex justify-center py-12">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="p-4 bg-red-50 text-red-700 rounded-lg">
        {error}
      </div>
    )
  }

  // This shouldn't normally be shown since we redirect, but as a fallback
  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-900">{project?.name}</h1>
      {project?.description && (
        <p className="mt-2 text-gray-600">{project.description}</p>
      )}
    </div>
  )
}
