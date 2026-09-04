import { useCallback, useEffect, useState } from 'react'
import { getLLMConfig } from '../api/llm'
import { LLMWizard } from '../components/llm-wizard/LLMWizard'

export function SettingsPage() {
  const [initialConfig, setInitialConfig] = useState<{ base_url: string; model: string } | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    getLLMConfig()
      .then((c) => {
        if (c.base_url && c.model) {
          setInitialConfig({ base_url: c.base_url, model: c.model })
        } else {
          setInitialConfig(null)
        }
      })
      .catch(() => {
        setInitialConfig(null)
      })
      .finally(() => {
        setLoading(false)
      })
  }, [])

  // Mantener initialConfig sincronizado con lo que el wizard guarda,
  // para que cualquier parte de SettingsPage que dependa del estado
  // (o un futuro unmount/remount) vea siempre la config persistida.
  const handleSaved = useCallback(
    (result: { model: string; baseUrl: string }) => {
      setInitialConfig({ base_url: result.baseUrl, model: result.model })
    },
    []
  )

  if (loading) {
    return (
      <div className="flex justify-center py-12">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
      </div>
    )
  }

  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-900 mb-6">
        Configuración Global del LLM
      </h1>
      <p className="text-gray-600 mb-6">
        Configura el proveedor de LLM que se utilizará en todos tus proyectos.
      </p>
      <LLMWizard initialConfig={initialConfig} onSaved={handleSaved} />
    </div>
  )
}
