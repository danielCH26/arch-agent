import type { ReactNode } from 'react'

interface PageHeaderProps {
  title: ReactNode
  subtitle?: ReactNode
  /** Botones a la derecha del título (p. ej. "Nuevo proyecto"). */
  actions?: ReactNode
}

/** Encabezado común de las páginas: mismo tamaño, peso y espaciado en todas. */
export function PageHeader({ title, subtitle, actions }: PageHeaderProps) {
  return (
    <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0">
        <h1 className="font-display text-2xl font-semibold text-gray-900 md:text-3xl">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-gray-500">{subtitle}</p>}
      </div>
      {actions}
    </div>
  )
}
