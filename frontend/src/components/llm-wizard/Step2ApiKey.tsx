import { useState } from 'react'

interface Step2ApiKeyProps {
  apiKey: string
  onChange: (value: string) => void
  onBack: () => void
  onNext: () => void
  loading: boolean
  error: string
}

export function Step2ApiKey({ apiKey, onChange, onBack, onNext, loading, error }: Step2ApiKeyProps) {
  const [showKey, setShowKey] = useState(false)
  const isValid = apiKey.trim().length >= 5

  return (
    <div>
      {error && (
        <div className="mb-4 p-3 bg-red-50 text-red-700 rounded-lg text-sm">{error}</div>
      )}

      <div className="space-y-4">
        <div>
          <label htmlFor="wizard-api-key" className="block text-sm font-medium text-gray-700 mb-1">
            API Key
          </label>
          <div className="relative">
            <input
              type={showKey ? 'text' : 'password'}
              id="wizard-api-key"
              value={apiKey}
              onChange={(e) => onChange(e.target.value)}
              placeholder="sk-..."
              disabled={loading}
              autoFocus
              className="w-full px-3 py-2 pr-10 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 disabled:bg-gray-50"
            />
            <button
              type="button"
              onClick={() => setShowKey(!showKey)}
              tabIndex={-1}
              className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-gray-400 hover:text-gray-600"
              aria-label={showKey ? 'Ocultar API key' : 'Mostrar API key'}
            >
              {showKey ? (
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
            Se utiliza para validar la conexión con el proveedor. No se guarda hasta confirmar el paso 3.
          </p>
        </div>
      </div>

      <div className="mt-6 flex justify-between gap-2">
        <button
          type="button"
          onClick={onBack}
          disabled={loading}
          className="px-4 py-2 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          Atrás
        </button>
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
