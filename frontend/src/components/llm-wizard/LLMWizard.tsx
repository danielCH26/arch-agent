import { useEffect, useState } from 'react'
import {
  wizardStep1,
  wizardStep2,
  wizardStep3,
  fetchAvailableModelsFromBackend,
} from '../../api/wizard'
import { ApiError as ClientApiError } from '../../api/client'
import { Step1BaseUrl } from './Step1BaseUrl'
import { Step2ApiKey } from './Step2ApiKey'
import { Step3ModelSelect } from './Step3ModelSelect'
import { tierFor, useBenchmarks } from './Step3ModelSelect'
import { SummaryView } from './SummaryView'

interface LLMWizardProps {
  initialConfig: { base_url: string; model: string } | null
  onSaved?: (result: { model: string; baseUrl: string }) => void
}

type Step = 1 | 2 | 3
type Mode = 'summary' | 'step1' | 'step2' | 'step3'

const STEP_LABELS: Record<Step, string> = {
  1: 'URL base',
  2: 'API Key',
  3: 'Modelo',
}

export function LLMWizard({ initialConfig, onSaved }: LLMWizardProps) {
  const [mode, setMode] = useState<Mode>(initialConfig ? 'summary' : 'step1')
  const [step, setStep] = useState<Step>(1)
  const [baseUrl, setBaseUrl] = useState(initialConfig?.base_url ?? '')
  const [apiKey, setApiKey] = useState('')
  const [availableModels, setAvailableModels] = useState<string[]>([])
  const [selectedModel, setSelectedModel] = useState('')
  const [freeTextMode, setFreeTextMode] = useState(false)
  const [freeTextValue, setFreeTextValue] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  const hasSavedConfig = Boolean(initialConfig)

  const clearError = () => setError('')

  // Benchmarks MMLU desde el backend (cacheados durante la vida del wizard).
  // Se usan para clasificar los modelos disponibles en tier1/tier2/unknown.
  const benchmarks = useBenchmarks()

  const loadAvailableModels = async (preferredModel?: string) => {
    try {
      const resp = await fetchAvailableModelsFromBackend()
      const filtered = resp.models.filter((m) => tierFor(m, benchmarks) !== 'blocked')
      setAvailableModels(filtered)
      const firstTier1 = filtered.find((m) => tierFor(m, benchmarks) === 'tier1')
      const fallbackModel = firstTier1 ?? filtered[0] ?? ''
      const initialModel =
        preferredModel && filtered.includes(preferredModel)
          ? preferredModel
          : fallbackModel
      setSelectedModel(initialModel)
      setFreeTextMode(false)
      setFreeTextValue('')
    } catch (err) {
      if (err instanceof ClientApiError && err.status === 404) {
        setError('No hay configuración guardada. Empezá por el paso 1.')
        setMode('step1')
        setStep(1)
        return
      }
      setError(err instanceof Error ? err.message : 'Error al obtener modelos disponibles')
      throw err
    }
  }

  useEffect(() => {
    if (mode === 'step3' && initialConfig) {
      setLoading(true)
      setError('')
      loadAvailableModels(initialConfig.model)
        .catch(() => {
          /* error ya seteado en loadAvailableModels */
        })
        .finally(() => {
          setLoading(false)
        })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode])

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
      setStep(3)
      setLoading(true)
      await loadAvailableModels()
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

  const handleChangeModel = () => {
    clearError()
    setSuccess('')
    setApiKey('')
    setMode('step3')
    setStep(3)
  }

  const handleChangeAll = () => {
    clearError()
    setSuccess('')
    setApiKey('')
    setMode('step1')
    setStep(1)
  }

  const handleBackToSummary = () => {
    clearError()
    setSuccess('')
    setApiKey('')
    setMode('summary')
    setStep(1)
  }

  const showStepIndicator = mode === 'step1' || mode === 'step2' || mode === 'step3'

  const stepIndicator = showStepIndicator ? (
    <ol className="flex items-center w-full mb-6 text-sm font-medium text-center text-gray-500 sm:text-base">
      {([1, 2, 3] as Step[]).map((s, idx) => {
        const isActive = s === step
        const isDone = s < step
        return (
          <li
            key={s}
            className={`flex items-center ${idx < 2 ? 'w-full' : ''} ${isActive || isDone ? 'text-blue-600' : ''}`}
          >
            <span
              className={`flex items-center justify-center w-8 h-8 mr-2 border rounded-full shrink-0 ${
                isActive
                  ? 'border-blue-600 bg-blue-50'
                  : isDone
                  ? 'border-blue-600 bg-blue-600 text-white'
                  : 'border-gray-300'
              }`}
            >
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
  ) : (
    <div className="mb-6 text-sm text-gray-500">Tu config actual</div>
  )

  const backToSummaryLink = hasSavedConfig && (mode === 'step2' || mode === 'step3') && (
    <button
      type="button"
      onClick={handleBackToSummary}
      disabled={loading}
      className="text-sm text-gray-500 hover:text-gray-700 disabled:opacity-50 mb-4 inline-flex items-center gap-1"
    >
      <span aria-hidden="true">←</span> Volver al resumen
    </button>
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

      {mode === 'summary' && initialConfig && (
        <SummaryView
          baseUrl={initialConfig.base_url}
          model={initialConfig.model}
          onChangeModel={handleChangeModel}
          onChangeAll={handleChangeAll}
          loading={loading}
        />
      )}

      {mode === 'step1' && (
        <Step1BaseUrl
          baseUrl={baseUrl}
          onChange={setBaseUrl}
          onNext={handleStep1Next}
          loading={loading}
          error={error}
        />
      )}

      {mode === 'step2' && (
        <div>
          {backToSummaryLink}
          <Step2ApiKey
            apiKey={apiKey}
            onChange={setApiKey}
            onBack={() => {
              clearError()
              setStep(1)
            }}
            onNext={handleStep2Next}
            loading={loading}
            error={error}
          />
        </div>
      )}

      {mode === 'step3' && (
        <div>
          {backToSummaryLink}
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
        </div>
      )}
    </div>
  )
}
