import { useState } from 'react'
import { wizardStep1, wizardStep2, wizardStep3, fetchAvailableModels } from '../../api/wizard'
import { Step1BaseUrl } from './Step1BaseUrl'
import { Step2ApiKey } from './Step2ApiKey'
import { Step3ModelSelect } from './Step3ModelSelect'
import { tierFor } from './Step3ModelSelect'

interface LLMWizardProps {
  initialBaseUrl: string | null
  onSaved?: (result: { model: string; baseUrl: string }) => void
}

type Step = 1 | 2 | 3

const STEP_LABELS: Record<Step, string> = {
  1: 'URL base',
  2: 'API Key',
  3: 'Modelo',
}

export function LLMWizard({ initialBaseUrl, onSaved }: LLMWizardProps) {
  const [step, setStep] = useState<Step>(1)
  const [baseUrl, setBaseUrl] = useState(initialBaseUrl ?? '')
  const [apiKey, setApiKey] = useState('')
  const [availableModels, setAvailableModels] = useState<string[]>([])
  const [selectedModel, setSelectedModel] = useState('')
  const [freeTextMode, setFreeTextMode] = useState(false)
  const [freeTextValue, setFreeTextValue] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  const clearError = () => setError('')

  const handleStep1Next = async () => {
    clearError()
    setLoading(true)
    try {
      await wizardStep1({ base_url: baseUrl.trim() })
      setStep(2)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error al validar URL')
    } finally {
      setLoading(false)
    }
  }

  const handleStep2Next = async () => {
    clearError()
    setLoading(true)
    try {
      await wizardStep2({ base_url: baseUrl.trim(), api_key: apiKey.trim() })
      const models = await fetchAvailableModels(baseUrl.trim(), apiKey.trim())
      const filtered = models.filter((m) => tierFor(m) !== 'blocked')
      setAvailableModels(filtered)
      const firstTier1 = filtered.find((m) => tierFor(m) === 'tier1')
      setSelectedModel(firstTier1 ?? filtered[0] ?? '')
      setFreeTextMode(false)
      setFreeTextValue('')
      setStep(3)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error al conectar con el proveedor')
    } finally {
      setLoading(false)
    }
  }

  const handleStep3Submit = async (model: string, allowUnknown: boolean) => {
    clearError()
    setLoading(true)
    try {
      const result = await wizardStep3({
        base_url: baseUrl.trim(),
        api_key: apiKey.trim(),
        model: model.trim(),
        allow_unknown_model: allowUnknown,
      })
      setSuccess(result.message || 'Configuración guardada.')
      onSaved?.({ model: result.model ?? model.trim(), baseUrl: result.base_url ?? baseUrl.trim() })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error al guardar configuración')
    } finally {
      setLoading(false)
    }
  }

  const stepIndicator = (
    <ol className="flex items-center w-full mb-6 text-sm font-medium text-center text-gray-500 sm:text-base">
      {([1, 2, 3] as Step[]).map((s, idx) => {
        const isActive = s === step
        const isDone = s < step
        return (
          <li
            key={s}
            className={`flex items-center ${idx < 2 ? 'w-full' : ''} ${isActive || isDone ? 'text-blue-600' : ''}`}
          >
            <span className={`flex items-center justify-center w-8 h-8 mr-2 border rounded-full shrink-0 ${
              isActive ? 'border-blue-600 bg-blue-50' : isDone ? 'border-blue-600 bg-blue-600 text-white' : 'border-gray-300'
            }`}>
              {isDone ? (
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
                </svg>
              ) : (
                s
              )}
            </span>
            <span className="hidden sm:inline">{STEP_LABELS[s]}</span>
            {idx < 2 && <span className="flex-1 h-px mx-3 bg-gray-200" />}
          </li>
        )
      })}
    </ol>
  )

  return (
    <div className="bg-white rounded-lg border border-gray-200 p-6">
      <h2 className="text-lg font-semibold text-gray-900 mb-1">Configuración de LLM</h2>
      <p className="text-sm text-gray-500 mb-6">
        Conectá el agente a un proveedor compatible con OpenAI en 3 pasos.
      </p>

      {stepIndicator}

      {success && (
        <div className="mb-4 p-3 bg-green-50 text-green-700 rounded-lg text-sm">{success}</div>
      )}

      {step === 1 && (
        <Step1BaseUrl
          baseUrl={baseUrl}
          onChange={setBaseUrl}
          onNext={handleStep1Next}
          loading={loading}
          error={error}
        />
      )}

      {step === 2 && (
        <Step2ApiKey
          apiKey={apiKey}
          onChange={setApiKey}
          onBack={() => { clearError(); setStep(1) }}
          onNext={handleStep2Next}
          loading={loading}
          error={error}
        />
      )}

      {step === 3 && (
        <Step3ModelSelect
          models={availableModels}
          selectedModel={selectedModel}
          onSelect={setSelectedModel}
          onCancelToFreeText={() => setFreeTextMode(true)}
          onSubmit={handleStep3Submit}
          freeTextMode={freeTextMode}
          freeTextValue={freeTextValue}
          onFreeTextChange={setFreeTextValue}
          onBackFromFreeText={() => setFreeTextMode(false)}
          loading={loading}
          error={error}
        />
      )}
    </div>
  )
}
