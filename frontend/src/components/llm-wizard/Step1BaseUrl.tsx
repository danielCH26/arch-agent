interface Step1BaseUrlProps {
  baseUrl: string
  onChange: (value: string) => void
  onNext: () => void
  loading: boolean
  error: string
}

export function Step1BaseUrl({ baseUrl, onChange, onNext, loading, error }: Step1BaseUrlProps) {
  const isValid = /^https?:\/\/.+/.test(baseUrl.trim())

  return (
    <div>
      {error && (
        <div className="mb-4 p-3 bg-red-50 text-red-700 rounded-lg text-sm">{error}</div>
      )}

      <div className="space-y-4">
        <div>
          <label htmlFor="wizard-base-url" className="block text-sm font-medium text-gray-700 mb-1">
            Base URL
          </label>
          <input
            type="text"
            id="wizard-base-url"
            value={baseUrl}
            onChange={(e) => onChange(e.target.value)}
            placeholder="https://api.openai.com/v1"
            disabled={loading}
            autoFocus
            className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 disabled:bg-gray-50"
          />
          <p className="mt-1 text-xs text-gray-500">
            URL del endpoint compatible con OpenAI. Ejemplo: https://api.openai.com/v1, https://api.anthropic.com
          </p>
        </div>
      </div>

      <div className="mt-6 flex justify-end">
        <button
          type="button"
          onClick={onNext}
          disabled={!isValid || loading}
          className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {loading ? 'Validando...' : 'Continuar'}
        </button>
      </div>
    </div>
  )
}
