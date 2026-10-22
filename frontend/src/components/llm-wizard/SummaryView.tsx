interface SummaryViewProps {
  baseUrl: string
  model: string
  onChangeModel: () => void
  onChangeAll: () => void
  loading?: boolean
}

export function SummaryView({ baseUrl, model, onChangeModel, onChangeAll, loading = false }: SummaryViewProps) {
  return (
    <div>
      <h3 className="text-base font-semibold text-gray-900 mb-4">Tu configuración actual</h3>

      <div className="bg-gray-50 rounded-lg border border-gray-200 p-4 space-y-3 mb-6">
        <div className="flex items-start gap-3">
          <svg
            className="w-5 h-5 mt-0.5 text-gray-500 shrink-0"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
            aria-hidden="true"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1"
            />
          </svg>
          <div className="min-w-0">
            <div className="text-xs font-medium text-gray-500">Proveedor (Base URL)</div>
            <div className="text-sm text-gray-900 break-all">{baseUrl}</div>
          </div>
        </div>

        <div className="flex items-start gap-3">
          <svg
            className="w-5 h-5 mt-0.5 text-gray-500 shrink-0"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
            aria-hidden="true"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M9 3v2m6-2v2M9 19v2m6-2v2M5 9H3m2 6H3m18-6h-2m2 6h-2M7 19h10a2 2 0 002-2V7a2 2 0 00-2-2H7a2 2 0 00-2 2v10a2 2 0 002 2zM9 9h6v6H9V9z"
            />
          </svg>
          <div className="min-w-0">
            <div className="text-xs font-medium text-gray-500">Modelo</div>
            <div className="text-sm text-gray-900 break-all">{model}</div>
          </div>
        </div>

        <div className="flex items-start gap-3">
          <svg
            className="w-5 h-5 mt-0.5 text-gray-500 shrink-0"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
            aria-hidden="true"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M15 7a2 2 0 012 2m4 0a6 6 0 01-7.743 5.743L11 17H9v2H7v2H4a1 1 0 01-1-1v-2.586a1 1 0 01.293-.707l5.964-5.964A6 6 0 1121 9z"
            />
          </svg>
          <div className="min-w-0">
            <div className="text-xs font-medium text-gray-500">API key</div>
            <div className="text-sm text-gray-900">•••••••• (guardada)</div>
          </div>
        </div>
      </div>

      <div className="flex flex-wrap justify-end gap-2">
        <button
          type="button"
          onClick={onChangeAll}
          disabled={loading}
          className="rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
        >
          Reconfigurar proveedor
        </button>
        <button
          type="button"
          onClick={onChangeModel}
          disabled={loading}
          className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 dark:hover:bg-solid-blue-700 disabled:cursor-not-allowed disabled:bg-gray-300"
        >
          Cambiar modelo
        </button>
      </div>

      <p className="mt-4 text-xs text-gray-500">
        Para cambiar el modelo, primero confirma que el proveedor sigue ofreciendo ese modelo.
      </p>
    </div>
  )
}
