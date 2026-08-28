import { useState, useEffect } from 'react'
import { getLLMConfig, saveLLMConfig, validateLLMConfig, LLMConfigResponse, LLMConfigSave, ValidateRequest } from '../api/llm'

export function LLMConfigForm() {
  const [config, setConfig] = useState<LLMConfigResponse | null>(null)
  const [baseUrl, setBaseUrl] = useState('')
  const [model, setModel] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [showApiKey, setShowApiKey] = useState(false)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [validating, setValidating] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [validationResult, setValidationResult] = useState<{ valid: boolean; message: string } | null>(null)

  useEffect(() => {
    getLLMConfig()
      .then((data) => {
        setConfig(data)
        setBaseUrl(data.base_url || '')
        setModel(data.model || '')
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : 'Error al cargar configuración')
      })
      .finally(() => {
        setLoading(false)
      })
  }, [])

  const handleValidate = async () => {
    if (!baseUrl.trim() || !apiKey.trim() || !model.trim()) {
      setError('Completa todos los campos para validar')
      return
    }

    // Validate URL format
    if (!/^https?:\/\/.+/.test(baseUrl)) {
      setError('La URL debe comenzar con http:// o https://')
      return
    }

    // Validate API key length
    if (apiKey.length < 5) {
      setError('La API key debe tener al menos 5 caracteres')
      return
    }

    setError('')
    setValidating(true)
    setValidationResult(null)

    try {
      const request: ValidateRequest = {
        base_url: baseUrl.trim(),
        api_key: apiKey.trim(),
        model: model.trim(),
      }
      const result = await validateLLMConfig(request)
      setValidationResult(result)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error al validar configuración')
    } finally {
      setValidating(false)
    }
  }

  const handleSave = async () => {
    if (!baseUrl.trim() || !model.trim()) {
      setError('URL y modelo son requeridos')
      return
    }

    setError('')
    setSaving(true)
    setSuccess('')

    try {
      const saveData: LLMConfigSave = {
        base_url: baseUrl.trim(),
        model: model.trim(),
        api_key: apiKey.trim(),
      }
      const result = await saveLLMConfig(saveData)
      setSuccess(result.message)
      setApiKey('') // Clear API key after save
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error al guardar configuración')
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <div className="flex justify-center py-8">
        <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-blue-600"></div>
      </div>
    )
  }

  return (
    <div className="bg-white rounded-lg border border-gray-200 p-6">
      <h2 className="text-lg font-semibold text-gray-900 mb-4">Configuración de LLM</h2>

      {error && (
        <div className="mb-4 p-3 bg-red-50 text-red-700 rounded-lg text-sm">
          {error}
        </div>
      )}

      {success && (
        <div className="mb-4 p-3 bg-green-50 text-green-700 rounded-lg text-sm">
          {success}
        </div>
      )}

      {validationResult && (
        <div className={`mb-4 p-3 rounded-lg text-sm ${
          validationResult.valid ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-700'
        }`}>
          {validationResult.message}
        </div>
      )}

      <div className="space-y-4">
        <div>
          <label htmlFor="baseUrl" className="block text-sm font-medium text-gray-700 mb-1">
            Base URL
          </label>
          <input
            type="text"
            id="baseUrl"
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
            placeholder="https://api.openai.com/v1"
            className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
          />
          <p className="mt-1 text-xs text-gray-500">
            Ejemplo: https://api.openai.com/v1, https://api.anthropic.com, etc.
          </p>
        </div>

        <div>
          <label htmlFor="model" className="block text-sm font-medium text-gray-700 mb-1">
            Modelo
          </label>
          <input
            type="text"
            id="model"
            value={model}
            onChange={(e) => setModel(e.target.value)}
            placeholder="gpt-4, claude-3-opus, etc."
            className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
          />
        </div>

        <div>
          <label htmlFor="apiKey" className="block text-sm font-medium text-gray-700 mb-1">
            API Key {config?.has_api_key && <span className="text-gray-400 font-normal">(guardada)</span>}
          </label>
          <div className="relative">
            <input
              type={showApiKey ? 'text' : 'password'}
              id="apiKey"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder={config?.has_api_key ? '••••••••' : 'sk-...'}
              className="w-full px-3 py-2 pr-10 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            />
            <button
              type="button"
              onClick={() => setShowApiKey(!showApiKey)}
              className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-gray-400 hover:text-gray-600"
            >
              {showApiKey ? (
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21" />
                </svg>
              ) : (
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                </svg>
              )}
            </button>
          </div>
          <p className="mt-1 text-xs text-gray-500">
            Déjalo vacío para mantener la clave actual
          </p>
        </div>
      </div>

      <div className="mt-6 flex gap-2">
        <button
          onClick={handleValidate}
          disabled={validating || !baseUrl.trim() || !apiKey.trim() || !model.trim()}
          className="px-4 py-2 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {validating ? 'Validando...' : 'Validar'}
        </button>
        <button
          onClick={handleSave}
          disabled={saving || !baseUrl.trim() || !model.trim()}
          className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {saving ? 'Guardando...' : 'Guardar'}
        </button>
      </div>
    </div>
  )
}
