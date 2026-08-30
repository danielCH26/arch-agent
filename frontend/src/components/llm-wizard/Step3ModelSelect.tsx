// Fallback hardcoded: si el fetch a /api/llm/benchmarks falla (offline,
// backend down, etc.), usamos estos scores locales para no bloquear al
// usuario. El backend es la fuente de verdad y se sincroniza via PR; este
// fallback es solo un safety net de ultima instancia.
//
// Si agregar un modelo aca, agregalo tambien en
// app/core/llm_model_benchmarks.json (fuente de verdad del backend).
const MODEL_MMLU_FALLBACK: Record<string, number> = {
  'gpt-4o': 88.7,
  'gpt-4-turbo': 86.5,
  'o1': 92.3,
  'o3-mini': 89.0,
  'o4-mini': 90.5,
  'claude-3-5-sonnet-latest': 88.7,
  'claude-3-7-sonnet': 89.3,
  'claude-sonnet-4': 91.5,
  'claude-opus-4': 92.5,
  'gemini-2.5-pro': 88.0,
  'gemini-2.0-pro': 86.5,
  'llama-3.1-405b-instruct': 88.6,
  'llama-3.3-70b-instruct': 86.0,
  'MiniMax-M3': 87.0,
  'gpt-4o-mini': 82.0,
  'claude-3-5-haiku': 75.2,
  'gemini-2.0-flash': 81.5,
}

const TIER1_THRESHOLD = 85
const TIER2_THRESHOLD = 60

export type ModelTier = 'tier1' | 'tier2' | 'blocked' | 'unknown'

export function tierFor(
  modelId: string,
  benchmarks: Record<string, number> = MODEL_MMLU_FALLBACK
): ModelTier {
  const score = benchmarks[modelId]
  if (score === undefined) return 'unknown'
  if (score >= TIER1_THRESHOLD) return 'tier1'
  if (score >= TIER2_THRESHOLD) return 'tier2'
  return 'blocked'
}

export function isBlocked(modelId: string): boolean {
  return tierFor(modelId) === 'blocked'
}

import { useEffect, useState } from 'react'
import { getBenchmarks } from '../../api/llm'

/**
 * Hook que fetcha los benchmarks MMLU desde el backend en /api/llm/benchmarks.
 * Devuelve el dict model -> score; si el fetch falla, devuelve el
 * fallback hardcoded (MODEL_MMLU_FALLBACK).
 *
 * Cachea durante toda la vida del componente (no re-fetchea en cada render).
 * Cuando el backend publica nuevos scores, hay que refrescar la pagina.
 */
export function useBenchmarks(): Record<string, number> {
  const [benchmarks, setBenchmarks] = useState<Record<string, number>>(MODEL_MMLU_FALLBACK)
  useEffect(() => {
    let cancelled = false
    getBenchmarks()
      .then((resp) => {
        if (cancelled) return
        const map: Record<string, number> = {}
        for (const entry of resp.models) {
          map[entry.model_id] = entry.mmlu_score
        }
        setBenchmarks(map)
      })
      .catch(() => {
        // Silencioso: ya estamos usando el fallback hardcoded.
      })
    return () => {
      cancelled = true
    }
  }, [])
  return benchmarks
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
  // Benchmarks dinamicos desde el backend (con fallback hardcoded si falla).
  const benchmarks = useBenchmarks()

  const recommended = models.filter((m) => tierFor(m, benchmarks) === 'tier1').sort()
  const other = models
    .filter((m) => {
      const t = tierFor(m, benchmarks)
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
    const allowUnknown = tierFor(selectedModel, benchmarks) !== 'tier1'
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
