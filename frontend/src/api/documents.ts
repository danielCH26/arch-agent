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

export async function uploadDocument(
  projectId: number,
  file: File,
  onProgress?: (progress: number) => void
): Promise<Document> {
  const token = authStore.getState().token
  const formData = new FormData()
  formData.append('file', file)

  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', `/api/documents/upload?project_id=${projectId}`)

    if (token) {
      xhr.setRequestHeader('Authorization', `Bearer ${token}`)
    }

    xhr.upload.addEventListener('progress', (event) => {
      if (event.lengthComputable && onProgress) {
        onProgress((event.loaded / event.total) * 100)
      }
    })

    xhr.addEventListener('load', () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(JSON.parse(xhr.responseText))
      } else {
        try {
          const data = JSON.parse(xhr.responseText)
          reject(new Error((data.detail as string) || 'Upload failed'))
        } catch {
          reject(new Error('Upload failed'))
        }
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
