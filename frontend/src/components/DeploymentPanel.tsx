import { useCallback, useEffect, useState } from 'react'
import {
  decideDeployment,
  fetchDeploymentHistory,
  generateDeployment,
  listCloudProviders,
  type CloudProvider,
  type DeploymentPlan,
  type DeploymentVersion,
} from '../api/deployments'

interface DeploymentPanelProps {
  projectId: number
  /** Hay un diagrama de arquitectura aprobado. Sin eso no se puede desplegar
   *  nada, así que el panel solo explica qué falta. */
  architectureApproved: boolean
  /** Aprobar el despliegue cierra la fase de Refinamiento: es su último
   *  paso. Hasta entonces "Avanzar fase" no aparece, así que no se puede
   *  saltar la nube. */
  onApproved?: () => void | Promise<void>
}

/**
 * Refinamiento, segundo paso: llevar la arquitectura aprobada a una nube.
 *
 * El flujo es elegir proveedor -> generar -> revisar el mapeo y el diagrama
 * -> aprobar o pedir cambios. La elección de nube es un paso explícito y no
 * un desplegable que genera al vuelo: el diagrama tarda y cada generación
 * queda guardada en el historial de versiones.
 */
export function DeploymentPanel({
  projectId,
  architectureApproved,
  onApproved,
}: DeploymentPanelProps) {
  const [providers, setProviders] = useState<CloudProvider[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [plan, setPlan] = useState<DeploymentPlan | null>(null)
  const [versions, setVersions] = useState<DeploymentVersion[]>([])
  const [generating, setGenerating] = useState(false)
  const [deciding, setDeciding] = useState(false)
  const [decided, setDecided] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [showFeedback, setShowFeedback] = useState(false)
  const [feedback, setFeedback] = useState('')

  const refreshHistory = useCallback(() => {
    fetchDeploymentHistory(projectId)
      .then(setVersions)
      .catch(() => undefined)
  }, [projectId])

  useEffect(() => {
    let cancelled = false
    listCloudProviders()
      .then(({ providers: found }) => {
        if (cancelled) return
        setProviders(found)
        // Con una sola nube habilitada no tiene sentido obligar a elegir.
        if (found.length === 1) setSelected(found[0].id)
      })
      .catch((err) =>
        setError(err instanceof Error ? err.message : 'No se pudieron cargar las nubes'),
      )
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    setPlan(null)
    setSelected(null)
    setDecided(null)
    refreshHistory()
  }, [projectId, refreshHistory])

  async function handleGenerate() {
    if (!selected) return
    setGenerating(true)
    setError('')
    setDecided(null)
    try {
      const result = await generateDeployment(projectId, selected)
      setPlan(result)
      refreshHistory()
    } catch (err) {
      setError(
        err instanceof Error && err.message
          ? err.message
          : 'No se pudo generar el diagrama de despliegue.',
      )
    } finally {
      setGenerating(false)
    }
  }

  async function handleDecision(decision: 'approve' | 'modify' | 'reject') {
    if (!plan?.attachment_id) return
    if (decision === 'modify' && !feedback.trim()) return
    setDeciding(true)
    setError('')
    try {
      const result = await decideDeployment(
        projectId,
        plan.attachment_id,
        decision,
        decision === 'modify' ? feedback.trim() : undefined,
      )
      setDecided(result.message)
      setShowFeedback(false)
      setFeedback('')
      refreshHistory()
      // Solo aprobar cierra la fase: pedir cambios o rechazar dejan
      // Refinamiento abierto, que es justo lo que se quiere.
      if (decision === 'approve') await onApproved?.()
    } catch (err) {
      setError(
        err instanceof Error && err.message ? err.message : 'No se pudo registrar la decisión.',
      )
    } finally {
      setDeciding(false)
    }
  }

  if (!architectureApproved) {
    return (
      <section
        data-testid="deployment-panel"
        className="rounded-xl border border-sky-200 bg-white p-4 shadow-sm"
      >
        <h2 className="text-base font-semibold text-gray-900">Despliegue en la nube</h2>
        <p className="mt-1 text-sm text-gray-600" data-testid="deployment-blocked">
          Aprueba primero el diagrama de arquitectura. El despliegue se calcula sobre la
          arquitectura aprobada.
        </p>
      </section>
    )
  }

  return (
    <section
      data-testid="deployment-panel"
      aria-labelledby="deployment-title"
      className="rounded-xl border border-sky-200 bg-white p-4 shadow-sm"
    >
      <h2 id="deployment-title" className="text-base font-semibold text-gray-900">
        Despliegue en la nube
      </h2>
      <p className="mt-1 text-xs text-gray-600">
        Lleva la arquitectura aprobada a servicios reales de una nube y muestra dónde queda
        cada pieza.
      </p>

      {/* Paso 1: elegir la nube */}
      <div className="mt-3 flex flex-wrap gap-2" role="radiogroup" aria-label="Proveedor de nube">
        {providers.map((provider) => {
          const isSelected = selected === provider.id
          return (
            <button
              key={provider.id}
              type="button"
              role="radio"
              aria-checked={isSelected}
              data-testid={`cloud-${provider.id}`}
              onClick={() => setSelected(provider.id)}
              className={
                isSelected
                  ? 'flex items-center gap-2 rounded-lg border-2 px-3 py-2 text-sm font-medium'
                  : 'flex items-center gap-2 rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-700 hover:bg-gray-100'
              }
              style={isSelected ? { borderColor: provider.color, color: provider.color } : undefined}
            >
              <span
                aria-hidden="true"
                className="h-3 w-3 rounded-full"
                style={{ backgroundColor: provider.color }}
              />
              {provider.name}
              <span className="text-xs text-gray-500">{provider.service_count} servicios</span>
            </button>
          )
        })}
      </div>

      <button
        type="button"
        data-testid="deployment-generate"
        disabled={!selected || generating}
        onClick={() => void handleGenerate()}
        className="mt-3 rounded-lg border border-sky-600 px-3 py-1.5 text-sm font-medium text-sky-700 hover:bg-sky-50 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {generating
          ? 'Generando el diagrama…'
          : plan
            ? 'Generar de nuevo'
            : 'Generar diagrama de despliegue'}
      </button>

      {error && (
        <div
          role="alert"
          data-testid="deployment-error"
          className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700"
        >
          {error}
        </div>
      )}

      {plan && (
        <div className="mt-4 space-y-4">
          {plan.url ? (
            <figure data-testid="deployment-diagram" className="rounded-lg border border-gray-100 p-3">
              <img
                src={plan.url}
                alt={`Diagrama de despliegue en ${plan.provider.name}`}
                className="h-auto w-full rounded object-contain"
              />
            </figure>
          ) : (
            <p className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-900">
              {plan.render_error ??
                'No se pudo generar la imagen; abajo queda el mapeo de componentes.'}
            </p>
          )}

          {/* Dónde se despliega cada pieza: el criterio de aceptación pide
              que esto se indique, no solo que se dibuje. */}
          <div>
            <h3 className="text-sm font-semibold text-gray-900">Dónde va cada pieza</h3>
            <table className="mt-2 w-full border-collapse text-left text-sm">
              <thead>
                <tr>
                  <th className="border border-gray-300 bg-gray-200 px-3 py-2 text-xs font-bold">
                    Componente
                  </th>
                  <th className="border border-gray-300 bg-gray-200 px-3 py-2 text-xs font-bold">
                    Servicio en {plan.provider.short_name}
                  </th>
                  <th className="border border-gray-300 bg-gray-200 px-3 py-2 text-xs font-bold">
                    Cómo desplegarlo
                  </th>
                </tr>
              </thead>
              <tbody>
                {plan.components.map((item) => (
                  <tr key={`${item.component}-${item.service_id}`} className="odd:bg-white even:bg-gray-50">
                    <td className="border border-gray-300 px-3 py-2 align-top">{item.component}</td>
                    <td className="border border-gray-300 px-3 py-2 align-top">
                      <span className="font-medium">{item.service_name}</span>
                      <span className="block text-xs text-gray-500">{item.category_label}</span>
                    </td>
                    <td className="border border-gray-300 px-3 py-2 align-top text-xs">
                      {item.deploy_note}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {plan.bridges.length > 0 && (
            <p className="text-xs text-gray-600" data-testid="deployment-bridges">
              <span className="font-medium">Agregado por {plan.provider.short_name}:</span>{' '}
              {plan.bridges.map((b) => b.service_name).join(', ')}. No sale de un componente de
              la arquitectura; hace falta para conectar las piezas en esta nube.
            </p>
          )}

          {plan.unmapped.length > 0 && (
            <p
              className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-900"
              data-testid="deployment-unmapped"
            >
              Sin equivalente directo en {plan.provider.short_name}:{' '}
              {plan.unmapped.join(', ')}. Revisa si hace falta un servicio específico o si esa
              pieza va dentro de otra.
            </p>
          )}

          {/* Paso 2: aprobar o pedir cambios */}
          {plan.attachment_id && !decided && (
            <div className="flex flex-wrap items-center gap-2 rounded-lg bg-sky-50 px-3 py-2">
              <p className="mr-auto text-sm text-sky-900">
                ¿El despliegue refleja lo que necesitas?
              </p>
              <button
                type="button"
                data-testid="deployment-approve"
                disabled={deciding}
                onClick={() => void handleDecision('approve')}
                className="rounded-lg border border-green-300 bg-white px-3 py-1.5 text-sm font-medium text-green-700 hover:bg-green-50 disabled:opacity-50"
              >
                Aprobar
              </button>
              <button
                type="button"
                data-testid="deployment-modify"
                disabled={deciding}
                onClick={() => setShowFeedback((open) => !open)}
                className="rounded-lg border border-sky-300 bg-white px-3 py-1.5 text-sm font-medium text-sky-700 hover:bg-sky-100 disabled:opacity-50"
              >
                Solicitar cambios
              </button>
              <button
                type="button"
                data-testid="deployment-reject"
                disabled={deciding}
                onClick={() => void handleDecision('reject')}
                className="rounded-lg border border-red-300 bg-white px-3 py-1.5 text-sm font-medium text-red-700 hover:bg-red-50 disabled:opacity-50"
              >
                Rechazar
              </button>
            </div>
          )}

          {showFeedback && !decided && (
            <div className="space-y-2">
              <label
                htmlFor={`deployment-feedback-${projectId}`}
                className="block text-sm font-medium text-gray-800"
              >
                ¿Qué cambiarías del despliegue?
              </label>
              <textarea
                id={`deployment-feedback-${projectId}`}
                value={feedback}
                onChange={(event) => setFeedback(event.target.value)}
                rows={3}
                maxLength={2000}
                placeholder="Por ejemplo: usar contenedores en vez de funciones para el worker…"
                className="w-full rounded-lg border border-gray-300 p-2 text-sm text-gray-900"
              />
              <button
                type="button"
                data-testid="deployment-send-feedback"
                disabled={deciding || !feedback.trim()}
                onClick={() => void handleDecision('modify')}
                className="rounded-lg border border-sky-600 px-3 py-1.5 text-sm font-medium text-sky-700 hover:bg-sky-50 disabled:opacity-50"
              >
                Enviar
              </button>
            </div>
          )}

          {decided && (
            <p
              role="status"
              data-testid="deployment-decided"
              className="rounded-lg bg-green-50 px-3 py-2 text-sm text-green-800"
            >
              {decided} Refinamiento queda cerrado: usa{' '}
              <span className="font-medium">Avanzar fase</span> arriba para pasar a Revisión.
            </p>
          )}
        </div>
      )}

      {versions.length > 0 && (
        <details className="mt-4" data-testid="deployment-history">
          <summary className="cursor-pointer text-sm font-medium text-sky-700">
            Historial de versiones ({versions.length})
          </summary>
          <ul className="mt-2 space-y-1">
            {versions.map((version) => (
              <li key={version.id} className="text-xs text-gray-600">
                <a href={version.url} target="_blank" rel="noreferrer" className="text-sky-700 underline">
                  {version.provider ? version.provider.toUpperCase() : 'Despliegue'}
                </a>{' '}
                · {new Date(version.created_at).toLocaleString()}
                {version.decision && ` · ${version.decision}`}
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  )
}
