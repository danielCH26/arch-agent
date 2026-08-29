import { useState, useRef } from 'react'
import { uploadDocument, DuplicateFileError } from '../api/documents'
import { DuplicateModal } from './DuplicateModal'

interface DocumentUploaderProps {
  projectId: number
  onUploadComplete: () => void
}

const ALLOWED_EXTENSIONS = ['.pdf', '.md']
const MAX_SIZE_MB = 10

export function DocumentUploader({ projectId, onUploadComplete }: DocumentUploaderProps) {
  const [isDragging, setIsDragging] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [progress, setProgress] = useState(0)
  const [error, setError] = useState('')
  const [pendingFile, setPendingFile] = useState<File | null>(null)
  const [duplicateInfo, setDuplicateInfo] = useState<{
    filename: string
    existing_version: number
  } | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const validateFile = (file: File): string | null => {
    const ext = '.' + file.name.split('.').pop()?.toLowerCase()
    if (!ALLOWED_EXTENSIONS.includes(ext)) {
      return `Tipo de archivo no permitido. Usa: ${ALLOWED_EXTENSIONS.join(', ')}`
    }
    if (file.size > MAX_SIZE_MB * 1024 * 1024) {
      return `El archivo excede el límite de ${MAX_SIZE_MB} MB`
    }
    return null
  }

  const doUpload = async (file: File, overwrite: boolean, suffix: boolean) => {
    setError('')
    setUploading(true)
    setProgress(0)
    try {
      await uploadDocument(projectId, file, {
        overwrite,
        suffix,
        onProgress: (p) => setProgress(p),
      })
      setPendingFile(null)
      setDuplicateInfo(null)
      onUploadComplete()
    } catch (err) {
      if (err instanceof DuplicateFileError) {
        setPendingFile(file)
        setDuplicateInfo({
          filename: err.info.filename,
          existing_version: err.info.existing_version,
        })
      } else {
        setError(err instanceof Error ? err.message : 'Error al subir archivo')
      }
    } finally {
      setUploading(false)
      setProgress(0)
    }
  }

  const handleUpload = async (file: File) => {
    const validationError = validateFile(file)
    if (validationError) {
      setError(validationError)
      return
    }
    await doUpload(file, false, false)
  }

  const handleReplace = async () => {
    if (!pendingFile) return
    await doUpload(pendingFile, true, false)
  }

  const handleSuffix = async () => {
    if (!pendingFile) return
    await doUpload(pendingFile, false, true)
  }

  const handleCancelDuplicate = () => {
    setPendingFile(null)
    setDuplicateInfo(null)
    setError('')
  }

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(false)

    const file = e.dataTransfer.files[0]
    if (file) {
      handleUpload(file)
    }
  }

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(true)
  }

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(false)
  }

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file) {
      handleUpload(file)
    }
    // Reset input so same file can be selected again
    if (fileInputRef.current) {
      fileInputRef.current.value = ''
    }
  }

  return (
    <div>
      <div
        onDrop={handleDrop}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onClick={() => fileInputRef.current?.click()}
        className={`
          border-2 border-dashed rounded-lg p-8 text-center cursor-pointer transition-colors
          ${isDragging ? 'border-blue-500 bg-blue-50' : 'border-gray-300 hover:border-gray-400'}
          ${uploading ? 'pointer-events-none opacity-50' : ''}
        `}
      >
        <input
          ref={fileInputRef}
          type="file"
          className="hidden"
          accept={ALLOWED_EXTENSIONS.join(',')}
          onChange={handleFileSelect}
          disabled={uploading}
        />

        {uploading ? (
          <div>
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600 mx-auto mb-2"></div>
            <p className="text-sm text-gray-600">Subiendo... {Math.round(progress)}%</p>
            <div className="mt-2 w-full bg-gray-200 rounded-full h-2">
              <div
                className="bg-blue-600 h-2 rounded-full transition-all"
                style={{ width: `${progress}%` }}
              ></div>
            </div>
          </div>
        ) : (
          <div>
            <svg className="mx-auto h-10 w-10 text-gray-400 mb-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
            </svg>
            <p className="text-sm text-gray-600">
              Arrastra un archivo aquí o haz clic para seleccionar
            </p>
            <p className="mt-1 text-xs text-gray-400">
              Archivos permitidos: PDF, Markdown (máx. {MAX_SIZE_MB} MB)
            </p>
          </div>
        )}
      </div>

      {error && (
        <div className="mt-2 p-3 bg-red-50 text-red-700 rounded-lg text-sm">
          {error}
        </div>
      )}

      {duplicateInfo && pendingFile && (
        <DuplicateModal
          filename={duplicateInfo.filename}
          existingVersion={duplicateInfo.existing_version}
          onReplace={handleReplace}
          onSuffix={handleSuffix}
          onCancel={handleCancelDuplicate}
          loading={uploading}
        />
      )}
    </div>
  )
}
