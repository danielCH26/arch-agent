// IMPORTANTE: esta lista DEBE estar sincronizada con
// app/core/llm_model_benchmarks.yaml. Si agregas un modelo aca, agregalo
// tambien en el YAML, o viceversa. Existe un test
// tests/api/test_llm_wizard_yaml_tsx_parity.py que falla automaticamente
// si se desincronizan.
//
// Fuente de cada score: ver campo `source` en el YAML. El backend usa el
// YAML como fuente de verdad para tier enforcement, este TSX es solo para
// la UI (mostrar badge "Recomendado" / "Sin score conocido").
const MODEL_MMLU: Record<string, number> = {
  // OpenAI
  'gpt-4o': 88.7,
  'gpt-4-turbo': 86.5,
  'o1': 92.3,
  'o3-mini': 89.0,
  'o4-mini': 90.5,
  // Anthropic
  'claude-3-5-sonnet-latest': 88.7,
  'claude-3-7-sonnet': 89.3,
  'claude-sonnet-4': 91.5,
  'claude-opus-4': 92.5,
  // Google
  'gemini-2.5-pro': 88.0,
  'gemini-2.0-pro': 86.5,
  // Meta
  'llama-3.1-405b-instruct': 88.6,
  'llama-3.3-70b-instruct': 86.0,
  // DeepSeek (chinos)
  'deepseek-v3': 88.5,
  'deepseek-r1': 90.8,
  'deepseek-v3.1': 88.6,
  // Qwen (Alibaba, chinos)
  'qwen-3-235b-a22b': 86.0,
  'qwen-2.5-72b-instruct': 86.4,
  // MiniMax (modelo del sistema)
  'MiniMax-M3': 87.0,
  // Tier 2
  'gpt-4o-mini': 82.0,
  'claude-3-5-haiku': 75.2,
  'gemini-2.0-flash': 81.5,
  'deepseek-v2.5': 80.4,
  'qwen-3-32b': 81.3,
  'qwen-2.5-32b-instruct': 75.6,
}

export type ModelTier = 'tier1' | 'tier2' | 'blocked' | 'unknown'

export function tierFor(modelId: string): ModelTier {
  const score = MODEL_MMLU[modelId]
  if (score === undefined) return 'unknown'
  if (score >= 85) return 'tier1'
  if (score >= 60) return 'tier2'
  return 'blocked'
}

export function isBlocked(modelId: string): boolean {
  return tierFor(modelId) === 'blocked'
}

interface Step3ModelSelectProps {
  models: string[]
  selectedModel: string
  onSelect: (model: string) => void
  onCancelToFreeText: () => void
  onSubmit: (model: string, allowUnknown: boolean) => void
  freeTextMode: boolean
  freeTextValue: string
  onFreeTextChange: (value: string) => void
  onBackFromFreeText: () => void
  loading: boolean
  error: string
}

export function Step3ModelSelect({
  models,
  selectedModel,
  onSelect,
  onCancelToFreeText,
  onSubmit,
  freeTextMode,
  freeTextValue,
  onFreeTextChange,
  onBackFromFreeText,
  loading,
  error,
}: Step3ModelSelectProps) {
  const recommended = models.filter((m) => tierFor(m) === 'tier1').sort()
  const other = models
    .filter((m) => {
      const t = tierFor(m)
      return t === 'tier2' || t === 'unknown'
    })
    .sort()

  const handleSubmit = () => {
    if (freeTextMode) {
      const v = freeTextValue.trim()
      if (!v) return
      onSubmit(v, true)
      return
    }
    if (!selectedModel) return
    const allowUnknown = tierFor(selectedModel) !== 'tier1'
    onSubmit(selectedModel, allowUnknown)
  }

  const submitDisabled = loading || (freeTextMode ? !freeTextValue.trim() : !selectedModel)

  return (
    <div>
      {error && (
        <div className="mb-4 p-3 bg-red-50 text-red-700 rounded-lg text-sm">{error}</div>
      )}

      {!freeTextMode ? (
        <div className="space-y-4">
          <div>
            <label htmlFor="wizard-model" className="block text-sm font-medium text-gray-700 mb-1">
              Modelo
            </label>
            <select
              id="wizard-model"
              value={selectedModel}
              onChange={(e) => onSelect(e.target.value)}
              disabled={loading || models.length === 0}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 disabled:bg-gray-50 bg-white"
            >
              {models.length === 0 && <option value="">Cargando modelos...</option>}
              {recommended.length > 0 && (
                <optgroup label="Recomendados (Tier 1)">
                  {recommended.map((m) => (
                    <option key={m} value={m}>{m}</option>
                  ))}
                </optgroup>
              )}
              {other.length > 0 && (
                <optgroup label="Sin score conocido">
                  {other.map((m) => (
                    <option key={m} value={m}>{m}</option>
                  ))}
                </optgroup>
              )}
            </select>
            <p className="mt-1 text-xs text-gray-500">
              Modelos en tier 1 (MMLU &gt;= 85) se aprueban automáticamente. Los demás requieren confirmación.
            </p>
          </div>

          <div>
            <button
              type="button"
              onClick={onCancelToFreeText}
              disabled={loading}
              className="text-sm text-blue-600 hover:text-blue-700 disabled:opacity-50"
            >
              No encuentro mi modelo — escribir manualmente
            </button>
          </div>
        </div>
      ) : (
        <div className="space-y-4">
          <div>
            <label htmlFor="wizard-model-freetext" className="block text-sm font-medium text-gray-700 mb-1">
              Modelo (texto libre)
            </label>
            <input
              type="text"
              id="wizard-model-freetext"
              value={freeTextValue}
              onChange={(e) => onFreeTextChange(e.target.value)}
              placeholder="Escribe el modelo exacto (ej: gpt-4o, claude-sonnet-4)"
              disabled={loading}
              autoFocus
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 disabled:bg-gray-50"
            />
            <p className="mt-1 text-xs text-gray-500">
              El nombre se enviará tal cual al backend con allow_unknown_model=true.
            </p>
          </div>

          <div>
            <button
              type="button"
              onClick={onBackFromFreeText}
              disabled={loading}
              className="text-sm text-blue-600 hover:text-blue-700 disabled:opacity-50"
            >
              Volver al listado
            </button>
          </div>
        </div>
      )}

      <div className="mt-6 flex justify-end gap-2">
        <button
          type="button"
          onClick={handleSubmit}
          disabled={submitDisabled}
          className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {loading ? 'Guardando...' : 'Guardar'}
        </button>
      </div>
    </div>
  )
}
