import { useCallback, useEffect, useState } from 'react'
import {
  fetchRepoStructureHistory,
  generateRepoStructure,
  type DetectedModule,
  type StructurePlan,
  type StructureVersion,
} from '../api/repoStructure'

interface RepoStructurePanelProps {
  projectId: number
  /** Hay un diagrama de arquitectura aprobado. Los módulos salen de ahí, así
   *  que sin diagrama el panel solo explica qué falta. */
  architectureApproved: boolean
}

/**
 * Árbol de carpetas del repositorio, a partir de los módulos del diagrama
 * aprobado, de la convención del stack y de los patrones por módulo.
 *
 * Dos cosas que el panel deja a la vista a propósito:
 *
 * - **Cada línea dice de dónde sale.** Las que trae la convención del stack y
 *   las que aporta un patrón se distinguen, y cada una enlaza su fuente. Es el
 *   criterio de aceptación de la historia: nada sin respaldo.
 * - **Lo que no se pudo decidir se dice.** Un módulo sin patrón aplicable, o
 *   un patrón que aplica pero que la convención no sabe dónde ubicar, salen
 *   como aviso. No se inventa una carpeta para tapar el hueco.
 *
 * Sin variantes `dark:` en las clases: tailwind.config.js redefine la paleta
 * bajo `.dark`, así que escribir `dark:bg-gray-900` invierte dos veces y deja
 * el panel en blanco. Es el error que dejó el ADR ilegible en modo oscuro.
 */
export function RepoStructurePanel({ projectId, architectureApproved }: RepoStructurePanelProps) {
  const [plan, setPlan] = useState<StructurePlan | null>(null)
  const [versions, setVersions] = useState<StructureVersion[]>([])
  const [generating, setGenerating] = useState(false)
  const [error, setError] = useState('')
  const [expanded, setExpanded] = useState<string | null>(null)

  const refreshHistory = useCallback(() => {
    fetchRepoStructureHistory(projectId)
      .then(setVersions)
      .catch(() => undefined)
  }, [projectId])

  useEffect(() => {
    if (!architectureApproved) return
    refreshHistory()
  }, [architectureApproved, refreshHistory])

  const handleGenerate = async () => {
    setGenerating(true)
    setError('')
    try {
      const result = await generateRepoStructure(projectId)
      setPlan(result)
      refreshHistory()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'No se pudo generar la estructura.')
    } finally {
      setGenerating(false)
    }
  }

  if (!architectureApproved) {
    return (
      <section
        aria-labelledby="repo-structure-title"
        className="rounded-xl border border-sky-200 bg-white p-4 shadow-sm"
      >
        <h2 id="repo-structure-title" className="text-base font-semibold text-gray-900">
          Estructura del repositorio
        </h2>
        <p className="mt-1 text-sm text-gray-600" data-testid="repo-structure-blocked">
          Aprueba primero el diagrama de arquitectura: los módulos del árbol de carpetas
          salen de ese diagrama.
        </p>
      </section>
    )
  }

  const conventions = [plan?.backend, plan?.frontend].filter(Boolean) as NonNullable<
    StructurePlan['backend']
  >[]

  return (
    <section
      aria-labelledby="repo-structure-title"
      className="rounded-xl border border-sky-200 bg-white p-4 shadow-sm"
    >
      <h2 id="repo-structure-title" className="text-base font-semibold text-gray-900">
        Estructura del repositorio
      </h2>
      <p className="mt-1 text-xs text-gray-600">
        Árbol de carpetas según la convención oficial de tu stack y el patrón que aplica a
        cada módulo. Cada línea enlaza la fuente de la que sale.
      </p>

      <button
        type="button"
        onClick={handleGenerate}
        disabled={generating}
        className="mt-3 rounded-lg border border-sky-600 px-3 py-1.5 text-sm font-medium text-sky-700 hover:bg-sky-50 disabled:cursor-not-allowed disabled:opacity-50"
        data-testid="repo-structure-generate"
      >
        {generating ? 'Generando…' : plan ? 'Volver a generar' : 'Generar estructura'}
      </button>

      {error && (
        <p
          className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700"
          data-testid="repo-structure-error"
        >
          {error}
        </p>
      )}

      {plan && (
        <div className="mt-4 space-y-4">
          {conventions.length > 0 && (
            <div data-testid="repo-structure-conventions" className="space-y-1">
              {conventions.map((convention) => (
                <p key={convention.convention_id} className="text-xs text-gray-600">
                  <span className="font-medium text-gray-900">{convention.name}</span>{' '}
                  {convention.summary}{' '}
                  {convention.matched_term && (
                    <span className="text-gray-500">
                      (reconocida por «{convention.matched_term}»)
                    </span>
                  )}{' '}
                  {convention.fuentes.map((fuente) => (
                    <a
                      key={fuente.url}
                      href={fuente.url}
                      target="_blank"
                      rel="noreferrer"
                      className="text-sky-700 underline"
                    >
                      {fuente.titulo}
                    </a>
                  ))}
                </p>
              ))}
            </div>
          )}

          <figure data-testid="repo-structure-tree">
            <figcaption className="text-sm font-semibold text-gray-900">
              Árbol propuesto
            </figcaption>
            <pre className="mt-2 overflow-x-auto rounded-lg border border-gray-200 bg-gray-50 p-3 text-xs leading-relaxed text-gray-800">
              {plan.tree_text}
            </pre>
          </figure>

          <div>
            <h3 className="text-sm font-semibold text-gray-900">
              Por qué cada carpeta está ahí
            </h3>
            <table className="mt-2 w-full border-collapse text-left text-sm">
              <thead>
                <tr>
                  <th className="border border-gray-300 bg-gray-200 px-3 py-2 text-xs font-bold">
                    Ruta
                  </th>
                  <th className="border border-gray-300 bg-gray-200 px-3 py-2 text-xs font-bold">
                    Sale de
                  </th>
                  <th className="border border-gray-300 bg-gray-200 px-3 py-2 text-xs font-bold">
                    Razón y fuente
                  </th>
                </tr>
              </thead>
              <tbody data-testid="repo-structure-lines">
                {plan.lines.map((line) => (
                  <tr key={line.path} className="odd:bg-white even:bg-gray-50">
                    <td className="border border-gray-300 px-3 py-2 align-top font-mono text-xs">
                      {line.path}
                    </td>
                    <td className="border border-gray-300 px-3 py-2 align-top text-xs">
                      {line.origin === 'patron' ? (
                        <span className="font-medium">{line.pattern_name}</span>
                      ) : (
                        <span className="text-gray-600">Convención del stack</span>
                      )}
                    </td>
                    <td className="border border-gray-300 px-3 py-2 align-top text-xs">
                      {line.note}{' '}
                      {line.source_url && (
                        <a
                          href={line.source_url}
                          target="_blank"
                          rel="noreferrer"
                          className="text-sky-700 underline"
                        >
                          {line.source_title}
                        </a>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div>
            <h3 className="text-sm font-semibold text-gray-900">Módulos detectados</h3>
            <ul className="mt-2 space-y-2" data-testid="repo-structure-modules">
              {plan.modules.map((module) => (
                <ModuleRow
                  key={module.name}
                  module={module}
                  open={expanded === module.name}
                  onToggle={() =>
                    setExpanded((current) => (current === module.name ? null : module.name))
                  }
                />
              ))}
            </ul>
          </div>

          {plan.warnings.length > 0 && (
            <div
              className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-900"
              data-testid="repo-structure-warnings"
            >
              <p className="font-medium">Pendientes de revisar</p>
              <ul className="mt-1 list-disc space-y-0.5 pl-4">
                {plan.warnings.map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {versions.length > 0 && (
        <div className="mt-4 border-t border-gray-200 pt-3">
          <h3 className="text-sm font-semibold text-gray-900">Versiones generadas</h3>
          <ul className="mt-2 space-y-1 text-xs text-gray-600" data-testid="repo-structure-history">
            {versions.map((version) => (
              <li key={version.id}>
                {new Date(version.created_at).toLocaleString()} ·{' '}
                {version.module_count} módulo{version.module_count === 1 ? '' : 's'}
                {version.backend_name ? ` · ${version.backend_name}` : ''}
                {version.frontend_name ? ` · ${version.frontend_name}` : ''}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  )
}

function ModuleRow({
  module,
  open,
  onToggle,
}: {
  module: DetectedModule
  open: boolean
  onToggle: () => void
}) {
  const sinUbicar = module.patterns.filter((pattern) => !pattern.placed)
  return (
    <li className="rounded-lg border border-gray-200 p-2">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className="flex w-full items-baseline justify-between gap-2 text-left"
      >
        <span className="text-sm font-medium text-gray-900">{module.name}</span>
        <span className="text-xs text-gray-500">
          {module.kind}
          {module.matched_term ? ` · por «${module.matched_term}»` : ' · tipo por omisión'}
        </span>
      </button>

      {open && (
        <div className="mt-2 space-y-1 text-xs text-gray-700">
          {module.uncovered_reason && (
            <p className="rounded bg-amber-50 px-2 py-1 text-amber-900">
              {module.uncovered_reason}
            </p>
          )}
          {module.patterns.map((pattern) => (
            <p key={`${pattern.pattern_name}-${pattern.role}`}>
              <span className="font-medium">{pattern.pattern_name}</span>
              {pattern.placed ? (
                <>
                  {' → '}
                  <span className="font-mono">{pattern.path}</span>
                </>
              ) : (
                <span className="text-amber-800"> (aplica, pero sin carpeta documentada)</span>
              )}
              {'. '}
              {pattern.justification}{' '}
              {pattern.source_url && (
                <a
                  href={pattern.source_url}
                  target="_blank"
                  rel="noreferrer"
                  className="text-sky-700 underline"
                >
                  {pattern.source_title}
                </a>
              )}
            </p>
          ))}
          {sinUbicar.length > 0 && (
            <p className="text-amber-800">
              {sinUbicar.length} patrón(es) aplicable(s) sin ubicación en la convención del
              stack.
            </p>
          )}
        </div>
      )}
    </li>
  )
}
