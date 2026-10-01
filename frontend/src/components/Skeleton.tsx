import type { ReactNode } from 'react'

/** Bloque gris animado que ocupa el lugar del contenido mientras carga. */
export function Skeleton({ className = '' }: { className?: string }) {
  return <div aria-hidden="true" className={`animate-pulse rounded bg-gray-200 ${className}`} />
}

/** Contenedor de esqueletos: el lector de pantalla anuncia `label`. */
export function SkeletonGroup({ label, className = '', children }: { label: string; className?: string; children: ReactNode }) {
  return (
    <div role="status" aria-busy="true" className={className}>
      <span className="sr-only">{label}</span>
      {children}
    </div>
  )
}

export function ProjectCardsSkeleton({ count = 3 }: { count?: number }) {
  return (
    <SkeletonGroup label="Cargando proyectos…" className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {Array.from({ length: count }, (_, index) => (
        <div key={index} className="rounded-[10px] border border-gray-300 bg-gray-50 p-5">
          <div className="flex items-start justify-between gap-3">
            <Skeleton className="h-6 w-2/3" />
            <Skeleton className="h-6 w-20 rounded-full" />
          </div>
          <div className="mt-4 space-y-2">
            <Skeleton className="h-4 w-1/2" />
            <Skeleton className="h-4 w-2/5" />
          </div>
          <div className="mt-4 flex items-center justify-between">
            <Skeleton className="h-3 w-24" />
            <Skeleton className="h-8 w-32 rounded-lg" />
          </div>
        </div>
      ))}
    </SkeletonGroup>
  )
}

export function SidebarProjectsSkeleton({ count = 3 }: { count?: number }) {
  return (
    <SkeletonGroup label="Cargando proyectos…" className="space-y-1">
      {Array.from({ length: count }, (_, index) => (
        <div key={index} className="flex items-center gap-2 px-3 py-2.5">
          <Skeleton className="h-5 w-5 rounded-full" />
          <Skeleton className="h-4 flex-1" />
        </div>
      ))}
    </SkeletonGroup>
  )
}

export function PatternListSkeleton({ count = 5 }: { count?: number }) {
  return (
    <SkeletonGroup label="Cargando patrones…" className="space-y-2">
      {Array.from({ length: count }, (_, index) => (
        <div key={index} className="rounded-xl border border-gray-200 bg-white p-4">
          <div className="flex items-start justify-between gap-2">
            <Skeleton className="h-5 w-1/2" />
            <Skeleton className="h-5 w-20 rounded-full" />
          </div>
          <Skeleton className="mt-2 h-4 w-full" />
          <Skeleton className="mt-1 h-4 w-4/5" />
        </div>
      ))}
    </SkeletonGroup>
  )
}

export function DocumentsPageSkeleton() {
  return (
    <SkeletonGroup label="Cargando documentos…">
      <Skeleton className="mb-6 h-8 w-72 max-w-full" />
      <Skeleton className="h-40 w-full rounded-xl" />
      <Skeleton className="mb-3 mt-8 h-6 w-48" />
      <div className="rounded-[10px] border border-gray-200">
        {Array.from({ length: 4 }, (_, index) => (
          <div key={index} className="flex items-center gap-4 border-b border-gray-200 px-3 py-3 last:border-b-0">
            <Skeleton className="h-4 w-4" />
            <Skeleton className="h-4 flex-1" />
            <Skeleton className="h-4 w-16" />
            <Skeleton className="h-4 w-20" />
          </div>
        ))}
      </div>
    </SkeletonGroup>
  )
}

export function ChatHistorySkeleton() {
  return (
    <SkeletonGroup label="Cargando historial del chat…" className="space-y-3">
      {[
        { user: false, width: 'w-3/5' },
        { user: true, width: 'w-2/5' },
        { user: false, width: 'w-1/2' },
      ].map(({ user, width }, index) => (
        <div key={index} className={`flex items-start gap-2 ${user ? 'justify-end' : 'justify-start'}`}>
          {!user && <Skeleton className="mt-1 h-9 w-9 rounded-full" />}
          <Skeleton className={`h-16 ${width} rounded-2xl`} />
        </div>
      ))}
    </SkeletonGroup>
  )
}
