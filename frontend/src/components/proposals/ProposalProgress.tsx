import { useEffect, useState } from 'react'
import { proposalsStore } from '../../stores/proposalsStore'

/** A partir de aquí se avisa que está tardando más de lo habitual. */
const SLOW_AFTER_S = 120

export function formatElapsed(totalSeconds: number): string {
  const safe = Math.max(0, Math.floor(totalSeconds))
  const minutes = Math.floor(safe / 60)
  const seconds = safe % 60
  return `${minutes}:${seconds.toString().padStart(2, '0')}`
}

/**
 * Indicador de progreso + botón "Cancelar" mientras se genera (o modifica) una
 * propuesta. Lee todo de `proposalsStore`: la etapa y el porcentaje de la barra
 * vienen de los eventos SSE `progress`; el tiempo transcurrido corre en el
 * cliente para avanzar cada segundo aunque el servidor tarde en emitir el
 * siguiente evento. Solo se muestra el tiempo transcurrido: el tope del
 * servidor (`budget_s`) no se enseña para no presentarlo como una cuenta atrás.
 */
export function ProposalProgress() {
  const inFlight = proposalsStore((s) => s.inFlight)
  const progress = proposalsStore((s) => s.progress)
  const startedAt = proposalsStore((s) => s.startedAt)
  const cancel = proposalsStore((s) => s.cancel)

  const active = inFlight === 'generating' || inFlight === 'modifying'
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    if (!active) return
    // Sin setNow síncrono aquí: el primer tick llega en 1 s y mientras tanto
    // `elapsedS` se recorta a 0 (formatElapsed no muestra negativos).
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [active, startedAt])

  if (!active) return null

  const elapsedS = startedAt ? Math.max(0, (now - startedAt) / 1000) : 0
  const percent = Math.min(100, Math.max(0, Math.round(progress?.percent ?? 0)))
  const label =
    progress?.message ??
    (inFlight === 'modifying' ? 'Aplicando los cambios solicitados' : 'Iniciando la generación')
  const slow = elapsedS >= SLOW_AFTER_S

  return (
    <div
      className="mb-3 rounded-md border border-blue-100 bg-blue-50 p-3"
      data-testid="proposal-progress"
    >
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm font-medium text-blue-900" data-testid="proposal-progress-label">
          {label}…
        </p>
        <button
          type="button"
          onClick={cancel}
          className="rounded border border-blue-300 bg-white px-3 py-1 text-xs font-semibold text-blue-800 hover:bg-blue-100"
          data-testid="proposal-cancel-generation"
          aria-label="Cancelar generación"
        >
          Cancelar
        </button>
      </div>

      <div
        role="progressbar"
        aria-label="Progreso de la generación"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent}
        className="mt-2 h-2 w-full overflow-hidden rounded bg-blue-100"
      >
        <div
          className="h-full rounded bg-blue-600 transition-all duration-500"
          style={{ width: `${percent}%` }}
          data-testid="proposal-progress-bar"
        />
      </div>

      <p className="mt-1 text-xs text-blue-800" data-testid="proposal-progress-time">
        Tiempo transcurrido: {formatElapsed(elapsedS)}
      </p>

      {slow && (
        <p className="mt-1 text-xs text-amber-700" role="status" data-testid="proposal-progress-slow">
          Está tardando más de lo habitual. Puedes cancelar e intentarlo de nuevo.
        </p>
      )}
    </div>
  )
}
