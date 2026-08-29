interface DuplicateModalProps {
  filename: string
  existingVersion: number
  onReplace: () => void
  onSuffix: () => void
  onCancel: () => void
  loading?: boolean
}

export function DuplicateModal({
  filename,
  existingVersion,
  onReplace,
  onSuffix,
  onCancel,
  loading = false,
}: DuplicateModalProps) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div
        className="absolute inset-0 bg-black bg-opacity-50"
        onClick={onCancel}
      ></div>
      <div className="relative bg-white rounded-lg shadow-xl p-6 max-w-md w-full">
        <h3 className="text-lg font-semibold text-gray-900">
          Archivo duplicado
        </h3>
        <p className="mt-2 text-sm text-gray-600">
          El archivo <strong>{filename}</strong> ya existe en este proyecto como{' '}
          <strong>v{existingVersion}</strong>. Elegí cómo continuar.
        </p>
        <div className="mt-5 flex flex-col gap-2">
          <button
            type="button"
            onClick={onReplace}
            disabled={loading}
            className="w-full px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            Reemplazar
          </button>
          <button
            type="button"
            onClick={onSuffix}
            disabled={loading}
            className="w-full px-4 py-2 bg-gray-100 text-gray-800 rounded-lg hover:bg-gray-200 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            Subir con sufijo
          </button>
          <button
            type="button"
            onClick={onCancel}
            disabled={loading}
            className="w-full px-4 py-2 text-gray-600 rounded-lg hover:bg-gray-100 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            Cancelar
          </button>
        </div>
      </div>
    </div>
  )
}