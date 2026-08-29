import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { getProject, Project } from '../api/projects'
import { getLLMConfig } from '../api/llm'
import { LLMWizard } from '../components/llm-wizard/LLMWizard'

export function SettingsPage() {
  const { id } = useParams<{ id: string }>()
  const [project, setProject] = useState<Project | null>(null)
  const [initialBaseUrl, setInitialBaseUrl] = useState<string | null>(null)
  const [projectLoading, setProjectLoading] = useState(true)
  const [llmLoading, setLlmLoading] = useState(true)

  useEffect(() => {
    const projectId = Number(id)
    if (!projectId || isNaN(projectId)) {
      setProjectLoading(false)
      return
    }

    getProject(projectId)
      .then((data) => {
        setProject(data)
      })
      .catch(() => {
        // Ignore error, show page anyway
      })
      .finally(() => {
        setProjectLoading(false)
      })
  }, [id])

  useEffect(() => {
    getLLMConfig()
      .then((c) => {
        setInitialBaseUrl(c.base_url)
      })
      .catch(() => {
        setInitialBaseUrl(null)
      })
      .finally(() => {
        setLlmLoading(false)
      })
  }, [])

  if (projectLoading || llmLoading) {
    return (
      <div className="flex justify-center py-12">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
      </div>
    )
  }

  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-900 mb-6">
        Configuración {project && `- ${project.name}`}
      </h1>
      <LLMWizard initialBaseUrl={initialBaseUrl} />
    </div>
  )
}
