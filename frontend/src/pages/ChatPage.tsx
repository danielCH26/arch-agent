import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { getProject, Project } from '../api/projects'
import { ChatWindow } from '../components/ChatWindow'
import { PhaseBadge } from '../components/PhaseBadge'

export function ChatPage() {
  const { id } = useParams<{ id: string }>()
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
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : 'Error al cargar el proyecto')
      })
      .finally(() => {
        setLoading(false)
      })
  }, [id])

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

  return (
    <div className="h-full flex flex-col">
      <div className="border-b border-gray-200 px-4 py-3 bg-white">
        <div className="flex items-center gap-3">
          <h1 className="text-xl font-semibold text-gray-900">{project?.name}</h1>
          <PhaseBadge phase={project?.current_phase || null} ready={project?.phase_ready || false} />
        </div>
      </div>
      <div className="flex-1 overflow-hidden">
        <ChatWindow projectId={Number(id)} />
      </div>
    </div>
  )
}
