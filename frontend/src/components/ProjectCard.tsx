import { useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Project } from '../api/projects'
import { useDialog } from '../hooks/useDialog'
import { PHASE_LABELS } from './phaseLabels'
import { formatDate } from '../lib/format'
import { projectsStore } from '../stores/projectsStore'

interface ProjectCardProps {
  project: Project
}


// Íconos de línea (Heroicons outline), como el resto de la interfaz.
const LAYERS_PATH =
  'M6.429 9.75L2.25 12l4.179 2.25m0-4.5l5.571 3 5.571-3m-11.142 0L2.25 7.5 12 2.25l9.75 5.25-4.179 2.25m0 0L21.75 12l-4.179 2.25m0 0l4.179 2.25L12 21.75 2.25 16.5l4.179-2.25m11.142 0l-5.571 3-5.571-3'
const CHECK_PATH = 'M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z'
const CLOCK_PATH = 'M12 6v6h4.5m4.5 0a9 9 0 11-18 0 9 9 0 0118 0z'

function CardIcon({ d, className }: { d: string; className: string }) {
  return (
    <svg aria-hidden="true" className={`h-4 w-4 shrink-0 ${className}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d={d} />
    </svg>
  )
}

function statusBadge(project: Project): { label: string; className: string } {
  // HU10: la última fase es `final` (antes era `revision`).
  if (project.current_phase === 'final' && project.phase_ready) {
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
  const cancelButtonRef = useRef<HTMLButtonElement>(null)

  const closeDeleteConfirm = () => setShowDeleteConfirm(false)

  // Diálogo de confirmación: foco en "Cancelar" (la opción segura), Esc
  // cierra y el foco vuelve al botón de eliminar.
  const dialogRef = useDialog({
    open: showDeleteConfirm,
    onClose: closeDeleteConfirm,
    initialFocusRef: cancelButtonRef,
    preventClose: isDeleting,
  })

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

  const badge = statusBadge(project)
  // HU10: el proyecto termina al aprobar la fase final (Cierre), no Revisión.
  const isComplete = project.current_phase === 'final' && project.phase_ready

  return (
    <div className="group rounded-[10px] border border-gray-300 bg-gray-50 p-5 shadow-[0px_2px_6px_0px_rgba(0,0,0,0.12)] transition-shadow hover:shadow-md">
      <div className="flex items-start justify-between gap-3">
        <h2 className="min-w-0 break-words text-xl font-semibold text-gray-900">
          <button
            type="button"
            onClick={() => navigate(`/projects/${project.id}`)}
            className="text-left hover:text-blue-600"
          >
            {project.name}
          </button>
        </h2>
        <div className="flex shrink-0 items-center gap-2">
          <span className={`whitespace-nowrap rounded-full px-3 py-1 text-xs font-medium ${badge.className}`}>
            {badge.label}
          </span>
          {/* Siempre visible en pantallas táctiles (celular y tablet); con
              ratón aparece al pasar el cursor o al recibir el foco
              (clase .reveal-on-hover en index.css). */}
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation()
              setShowDeleteConfirm(true)
            }}
            className="reveal-on-hover rounded p-1 text-gray-500 transition-opacity hover:text-red-600"
            title="Eliminar proyecto"
            aria-label={`Eliminar proyecto ${project.name}`}
          >
            <svg aria-hidden="true" className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
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
          <CardIcon d={LAYERS_PATH} className="text-gray-500" />
          <span>Fase: {PHASE_LABELS[project.current_phase || ''] || 'Sin fase'}</span>
        </div>
        <div className="flex items-center gap-2">
          {project.phase_ready ? (
            <CardIcon d={CHECK_PATH} className="text-emerald-600" />
          ) : (
            <CardIcon d={CLOCK_PATH} className="text-gray-500" />
          )}
          {/* En la última fase, "lista" significa que el proyecto terminó. */}
          <span>{isComplete ? 'Arquitectura aprobada' : project.phase_ready ? 'Lista para avanzar' : 'En progreso'}</span>
        </div>
      </div>

      <div className="mt-4 flex items-center justify-between gap-3">
        <span className="text-xs text-gray-500">Creado: {formatDate(project.created_at)}</span>
        <button
          onClick={() => navigate(`/projects/${project.id}/chat`)}
          className={
            isComplete
              ? 'shrink-0 whitespace-nowrap rounded-lg bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 dark:hover:bg-solid-blue-700'
              : 'shrink-0 whitespace-nowrap rounded-lg border border-blue-600 px-3 py-1.5 text-sm font-medium text-blue-700 hover:bg-blue-50'
          }
        >
          {isComplete ? 'Ver arquitectura' : 'Continuar'}
        </button>
      </div>

      {showDeleteConfirm && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div
            ref={dialogRef}
            role="alertdialog"
            aria-modal="true"
            aria-labelledby={`delete-title-${project.id}`}
            aria-describedby={`delete-desc-${project.id}`}
            className="mx-4 w-full max-w-sm rounded-lg bg-white p-6"
          >
            <h2 id={`delete-title-${project.id}`} className="text-lg font-semibold text-gray-900">Confirmar eliminación</h2>
            <p id={`delete-desc-${project.id}`} className="mt-2 text-gray-600">
              ¿Estás seguro de eliminar "{project.name}"? Esta acción no se puede deshacer.
            </p>
            <div className="mt-4 flex justify-end gap-2">
              <button
                ref={cancelButtonRef}
                type="button"
                onClick={closeDeleteConfirm}
                className="rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
                disabled={isDeleting}
              >
                Cancelar
              </button>
              <button
                type="button"
                onClick={handleDelete}
                className="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 dark:hover:bg-solid-red-700 disabled:opacity-50"
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
