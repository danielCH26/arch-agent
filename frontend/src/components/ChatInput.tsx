import { useState, useRef, useEffect } from 'react'
import { uploadDocument, DuplicateFileError } from '../api/documents'
import { chatStore } from '../stores/chatStore'
import { DuplicateModal } from './DuplicateModal'

interface ChatInputProps {
  projectId: number
  onSend: (text: string) => void
  disabled?: boolean
}

const ALLOWED_EXTENSIONS = ['.pdf', '.md']
const MAX_SIZE_MB = 10

export function ChatInput({
  projectId,
  onSend,
  disabled = false,
}: ChatInputProps) {
  const [text, setText] = useState('')
  const [uploading, setUploading] = useState(false)
  const [progress, setProgress] = useState(0)
  const [uploadError, setUploadError] = useState('')
  const [pendingFile, setPendingFile] = useState<File | null>(null)
  const [duplicateInfo, setDuplicateInfo] = useState<{
    filename: string
    existing_version: number
  } | null>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
      const newHeight = Math.min(textareaRef.current.scrollHeight, 4 * 24)
      textareaRef.current.style.height = `${newHeight}px`
    }
  }, [text])

  const handleSend = () => {
    if (!text.trim() || disabled) return
    onSend(text.trim())
    setText('')
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    handleSend()
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

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
    setUploadError('')
    setUploading(true)
    setProgress(0)
    try {
      const doc = await uploadDocument(projectId, file, {
        overwrite,
        suffix,
        onProgress: (p) => setProgress(p),
      })
      chatStore.getState().addSystemMessage(`[Adjunto: ${doc.filename}] subido al proyecto`)
      setPendingFile(null)
      setDuplicateInfo(null)
    } catch (err) {
      if (err instanceof DuplicateFileError) {
        setPendingFile(file)
        setDuplicateInfo({
          filename: err.info.filename,
          existing_version: err.info.existing_version,
        })
      } else {
        setUploadError(err instanceof Error ? err.message : 'Error al subir archivo')
      }
    } finally {
      setUploading(false)
      setProgress(0)
    }
  }

  const handleAttach = async (file: File) => {
    if (uploading || disabled) return
    const validationError = validateFile(file)
    if (validationError) {
      setUploadError(validationError)
      return
    }
    await doUpload(file, false, false)
  }

  const handleClipClick = () => {
    fileInputRef.current?.click()
  }

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file) {
      handleAttach(file)
    }
    if (fileInputRef.current) {
      fileInputRef.current.value = ''
    }
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
    setUploadError('')
  }

  return (
    <form onSubmit={handleSubmit} className="border-t border-gray-200 p-4 bg-white">
      {/* Textarea con auto-resize */}
      <textarea
        ref={textareaRef}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="Escribe un mensaje..."
        disabled={disabled}
        rows={1}
        className="flex-1 px-4 py-2 border border-gray-300 rounded-lg resize-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500 disabled:bg-gray-100 disabled:text-gray-500"
      />

      {/* Contenedor de la caja de texto + clip */}
      <div className="flex gap-2 items-end">
        <button
          type="button"
          onClick={handleClipClick}
          disabled={uploading || disabled}
          title="Adjuntar archivo (PDF o MD)"
          className="p-2 text-gray-500 hover:text-gray-700 rounded-lg hover:bg-gray-100 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" />
          </svg>
        </button>
        <input
          ref={fileInputRef}
          type="file"
          className="hidden"
          accept={ALLOWED_EXTENSIONS.join(',')}
          onChange={handleFileSelect}
          disabled={uploading}
        />
        <button
          type="submit"
          disabled={disabled || !text.trim() || uploading}
          className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
          </svg>
        </button>
      </div>

      {/* Progreso de upload */}
      {uploading && (
        <div className="mt-2">
          <p className="text-xs text-gray-600">Subiendo adjunto... {Math.round(progress)}%</p>
          <div className="mt-1 w-full bg-gray-200 rounded-full h-1.5">
            <div
              className="bg-blue-600 h-1.5 rounded-full transition-all"
              style={{ width: `${progress}%` }}
            ></div>
          </div>
        </div>
      )}

      {/* Error de upload */}
      {uploadError && (
        <div className="mt-2 p-3 bg-red-50 text-red-700 rounded-lg text-sm">
          {uploadError}
        </div>
      )}

      <p className="mt-1 text-xs text-gray-500">
        Presiona Enter para enviar, Shift+Enter para nueva línea. Adjunta PDF o MD con el clip.
      </p>

      {/* Modal de duplicados: 3 opciones */}
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
    </form>
  )
}