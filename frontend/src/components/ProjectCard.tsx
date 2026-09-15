import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Project } from '../api/projects'
import { projectsStore } from '../stores/projectsStore'

interface ProjectCardProps {
  project: Project
}

const PHASE_LABELS: Record<string, string> = {
  requerimientos: 'Requerimientos',
  propuesta: 'Propuesta',
  refinamiento: 'Refinamiento',
  revision: 'Revisión',
}

function statusBadge(project: Project): { label: string; className: string } {
  if (project.current_phase === 'revision' && project.phase_ready) {
    return { label: 'Completado', className: 'bg-green-100 text-green-800' }
  }
  if (project.current_phase === 'requerimientos') {
    return { label: 'En elicitación', className: 'bg-blue-100 text-blue-800' }
  }
  if (project.current_phase === 'revision') {
    return { label: 'Revisión', className: 'bg-orange-100 text-orange-800' }
  }
  return { label: PHASE_LABELS[project.current_phase || ''] || 'Sin fase', className: 'bg-gray-100 text-gray-700' }
}

export function ProjectCard({ project }: ProjectCardProps) {
  const navigate = useNavigate()
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)
  const [isDeleting, setIsDeleting] = useState(false)

  const handleDelete = async () => {
    setIsDeleting(true)
    try {
      await projectsStore.getState().deleteProject(project.id)
    } catch {
      // Error is handled in store
    } finally {
      setIsDeleting(false)
      setShowDeleteConfirm(false)
    }
  }

  const formatDate = (dateString: string) => {
    return new Date(dateString).toLocaleDateString('es-AR', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    })
  }

  const badge = statusBadge(project)
  const isComplete = project.current_phase === 'revision' && project.phase_ready

  return (
    <div className="group rounded-[10px] border border-gray-300 bg-[#fafafa] p-5 shadow-[0px_2px_6px_0px_rgba(0,0,0,0.12)] transition-shadow hover:shadow-md">
      <div className="flex items-start justify-between gap-3">
        <h3
          className="cursor-pointer text-xl font-semibold text-gray-900 hover:text-blue-600"
          onClick={() => navigate(`/projects/${project.id}`)}
        >
          {project.name}
        </h3>
        <div className="flex shrink-0 items-center gap-2">
          <span className={`whitespace-nowrap rounded-full px-3 py-1 text-xs font-medium ${badge.className}`}>
            {badge.label}
          </span>
          <button
            onClick={(e) => {
              e.stopPropagation()
              setShowDeleteConfirm(true)
            }}
            className="p-1 text-gray-300 opacity-0 transition-opacity hover:text-red-600 group-hover:opacity-100"
            title="Eliminar proyecto"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
            </svg>
          </button>
        </div>
      </div>

      {project.description && (
        <p className="mt-1 text-sm text-gray-500 line-clamp-2">{project.description}</p>
      )}

      <div className="mt-4 space-y-2 text-sm text-gray-700">
        <div className="flex items-center gap-2">
          <span aria-hidden="true">📚</span>
          <span>Fase: {PHASE_LABELS[project.current_phase || ''] || 'Sin fase'}</span>
        </div>
        <div className="flex items-center gap-2">
          <span aria-hidden="true">{project.phase_ready ? '✅' : '🕓'}</span>
          <span>{project.phase_ready ? 'Lista para avanzar' : 'En progreso'}</span>
        </div>
      </div>

      <div className="mt-4 flex items-center justify-between">
        <span className="text-xs text-gray-400">Creado: {formatDate(project.created_at)}</span>
        <button
          onClick={() => navigate(`/projects/${project.id}/chat`)}
          className={
            isComplete
              ? 'rounded-lg bg-blue-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-blue-700'
              : 'rounded-lg border border-blue-600 px-4 py-1.5 text-sm font-medium text-blue-700 hover:bg-blue-50'
          }
        >
          {isComplete ? 'Ver arquitectura' : 'Continuar sesión'}
        </button>
      </div>

      {showDeleteConfirm && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg p-6 max-w-sm mx-4">
            <h3 className="text-lg font-semibold text-gray-900">Confirmar eliminación</h3>
            <p className="mt-2 text-gray-600">
              ¿Estás seguro de eliminar "{project.name}"? Esta acción no se puede deshacer.
            </p>
            <div className="mt-4 flex justify-end gap-2">
              <button
                onClick={() => setShowDeleteConfirm(false)}
                className="px-4 py-2 text-gray-700 hover:bg-gray-100 rounded-lg"
                disabled={isDeleting}
              >
                Cancelar
              </button>
              <button
                onClick={handleDelete}
                className="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50"
                disabled={isDeleting}
              >
                {isDeleting ? 'Eliminando...' : 'Eliminar'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
