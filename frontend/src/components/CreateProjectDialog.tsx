import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useDialog } from '../hooks/useDialog'
import { projectsStore } from '../stores/projectsStore'

interface CreateProjectDialogProps {
  isOpen: boolean
  onClose: () => void
}

export function CreateProjectDialog({ isOpen, onClose }: CreateProjectDialogProps) {
  const navigate = useNavigate()
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [isCreating, setIsCreating] = useState(false)
  const [error, setError] = useState('')

  const handleClose = () => {
    if (!isCreating) {
      onClose()
      setName('')
      setDescription('')
      setError('')
    }
  }

  const dialogRef = useDialog({ open: isOpen, onClose: handleClose, preventClose: isCreating })

  if (!isOpen) return null

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()

    if (!name.trim()) {
      setError('El nombre es requerido')
      return
    }

    setIsCreating(true)
    setError('')

    try {
      const newProject = await projectsStore.getState().createProject(
        name.trim(),
        description.trim() || undefined
      )
      onClose()
      setName('')
      setDescription('')
      navigate(`/projects/${newProject.id}`)
    } catch (err) {
      setError(err instanceof Error && err.message ? err.message : 'No se pudo crear el proyecto.')
    } finally {
      setIsCreating(false)
    }
  }

  return (
    <div
      className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50"
      onClick={(e) => {
        if (e.target === e.currentTarget) handleClose()
      }}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="create-project-title"
        className="bg-white rounded-lg p-6 w-full max-w-md mx-4"
      >
        <h2 id="create-project-title" className="font-display text-xl font-semibold text-gray-900 mb-4">
          Nuevo proyecto
        </h2>

        <form onSubmit={handleSubmit}>
          <div className="mb-4">
            <label htmlFor="name" className="block text-sm font-medium text-gray-700 mb-1">
              Nombre *
            </label>
            <input
              type="text"
              id="name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              placeholder="Mi proyecto"
              disabled={isCreating}
            />
          </div>

          <div className="mb-4">
            <label htmlFor="description" className="block text-sm font-medium text-gray-700 mb-1">
              Descripción
            </label>
            <textarea
              id="description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              placeholder="Descripción opcional del proyecto"
              rows={3}
              disabled={isCreating}
            />
          </div>

          {error && (
            <div role="alert" className="mb-4 p-3 bg-red-50 text-red-700 rounded-lg text-sm">
              {error}
            </div>
          )}

          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={handleClose}
              className="px-4 py-2 text-gray-700 hover:bg-gray-100 rounded-lg disabled:opacity-50"
              disabled={isCreating}
            >
              Cancelar
            </button>
            <button
              type="submit"
              className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 dark:hover:bg-solid-blue-700 disabled:opacity-50"
              disabled={isCreating || !name.trim()}
            >
              {isCreating ? 'Creando...' : 'Crear'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
