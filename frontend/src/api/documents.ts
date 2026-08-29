import { apiFetch } from './client'
import { authStore } from '../stores/authStore'

export interface Document {
  id: number
  filename: string
  file_type: string
  file_size_bytes: number
  chunk_count: number
  version: number
  created_at: string
}

export async function listDocuments(projectId: number): Promise<Document[]> {
  return apiFetch<Document[]>(`/api/documents/${projectId}`)
}

export interface DuplicateInfo {
  is_duplicate: boolean
  existing_version: number
  filename: string
  detail: string
}

/**
 * Detectado cuando el backend retorna 409 al subir un archivo duplicado.
 * El frontend debe mostrar un modal de confirmacion y reintentar con
 * `overwrite=true` si el usuario acepta.
 */
export class DuplicateFileError extends Error {
  readonly info: DuplicateInfo
  constructor(info: DuplicateInfo) {
    super(info.detail)
    this.name = 'DuplicateFileError'
    this.info = info
  }
}

export async function uploadDocument(
  projectId: number,
  file: File,
  options?: { overwrite?: boolean; onProgress?: (progress: number) => void }
): Promise<Document> {
  const token = authStore.getState().token
  const overwrite = options?.overwrite ?? false
  const onProgress = options?.onProgress
  const formData = new FormData()
  formData.append('file', file)

  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    const url = overwrite
      ? `/api/documents/upload?project_id=${projectId}&overwrite=true`
      : `/api/documents/upload?project_id=${projectId}`

    xhr.open('POST', url)

    if (token) {
      xhr.setRequestHeader('Authorization', `Bearer ${token}`)
    }

    xhr.upload.addEventListener('progress', (event) => {
      if (event.lengthComputable && onProgress) {
        onProgress((event.loaded / event.total) * 100)
      }
    })

    xhr.addEventListener('load', () => {
      // 2xx: OK
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(JSON.parse(xhr.responseText))
        return
      }

      // 409: duplicado. Devolvemos DuplicateFileError para que el caller
      // muestre un modal de confirmacion y reintente con overwrite=true.
      if (xhr.status === 409) {
        try {
          const body = JSON.parse(xhr.responseText) as DuplicateInfo
          reject(new DuplicateFileError(body))
        } catch {
          reject(new Error('Duplicate file'))
        }
        return
      }

      // Otros errores
      try {
        const data = JSON.parse(xhr.responseText)
        reject(new Error((data.detail as string) || 'Upload failed'))
      } catch {
        reject(new Error('Upload failed'))
      }
    })

    xhr.addEventListener('error', () => {
      reject(new Error('Network error'))
    })

    xhr.send(formData)
  })
}

export async function deleteDocument(docId: number): Promise<void> {
  await apiFetch<void>(`/api/documents/${docId}`, {
    method: 'DELETE',
  })
}
