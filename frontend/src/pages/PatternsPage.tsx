import { useEffect, useMemo, useState } from 'react'
import { listPatterns, listPatternSourceChunks, Pattern, PatternSourceChunk } from '../api/patterns'

const PAGE_SIZE = 200 // máximo permitido por GET /api/patterns

async function fetchAllPatterns(): Promise<Pattern[]> {
  const items: Pattern[] = []
  let total = Infinity
  while (items.length < total) {
    const page = await listPatterns(PAGE_SIZE, items.length)
    total = page.total
    items.push(...page.items)
    if (page.items.length === 0) break
  }
  return items
}

export function PatternsPage() {
  const [patterns, setPatterns] = useState<Pattern[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [query, setQuery] = useState('')
  const [category, setCategory] = useState('')
  const [selectedId, setSelectedId] = useState<number | null>(null)

  useEffect(() => {
    fetchAllPatterns()
      .then(setPatterns)
      .catch((err) => setError(err instanceof Error ? err.message : 'Error al cargar los patrones'))
      .finally(() => setLoading(false))
  }, [])

  const categories = useMemo(
    () => Array.from(new Set(patterns.map((p) => p.category).filter((c): c is string => !!c))).sort(),
    [patterns],
  )

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return patterns.filter((p) => {
      if (category && p.category !== category) return false
      if (!needle) return true
      return [p.pattern_name, p.description, p.use_cases].some((text) => text?.toLowerCase().includes(needle))
    })
  }, [patterns, query, category])

  const selected = patterns.find((p) => p.id === selectedId) ?? null

  return (
    <div className="mx-auto max-w-6xl">
      <div className="mb-6">
        <h1 className="text-2xl font-semibold text-gray-900">Base de patrones</h1>
        <p className="mt-1 text-sm text-gray-500">
          Catálogo curado de patrones arquitectónicos. El asistente los consulta automáticamente (RAG) al elaborar propuestas.
        </p>
      </div>

      <div className="mb-4 flex flex-wrap gap-3">
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Buscar por nombre, descripción o caso de uso..."
          className="min-w-60 flex-1 rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm outline-none focus:border-sky-500"
        />
        <select
          value={category}
          onChange={(e) => setCategory(e.target.value)}
          className="rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-700"
          aria-label="Filtrar por categoría"
        >
          <option value="">Todas las categorías</option>
          {categories.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
      </div>

      {loading && (
        <div className="flex justify-center py-12">
          <div className="h-8 w-8 animate-spin rounded-full border-b-2 border-blue-600" />
        </div>
      )}

      {error && <div className="rounded-lg bg-red-50 p-4 text-red-700">{error}</div>}

      {!loading && !error && (
        <div className="grid gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
          <ul className="space-y-2">
            {filtered.map((p) => (
              <li key={p.id}>
                <button
                  type="button"
                  onClick={() => setSelectedId(p.id)}
                  className={`w-full rounded-xl border p-4 text-left transition-colors ${
                    selectedId === p.id ? 'border-sky-400 bg-sky-50' : 'border-gray-200 bg-white hover:border-sky-200'
                  }`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <span className="font-medium text-gray-900">{p.pattern_name}</span>
                    {p.category && <span className="shrink-0 rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-600">{p.category}</span>}
                  </div>
                  {p.description && <p className="mt-1 line-clamp-2 text-sm text-gray-500">{p.description}</p>}
                </button>
              </li>
            ))}
            {filtered.length === 0 && (
              <li className="py-8 text-center text-sm text-gray-500">
                {patterns.length === 0 ? 'El catálogo está vacío. Ejecuta scripts/seed_patterns.py para poblarlo.' : 'Ningún patrón coincide con la búsqueda.'}
              </li>
            )}
          </ul>

          <div className="lg:sticky lg:top-0 lg:self-start">
            {selected ? (
              <PatternDetail pattern={selected} />
            ) : (
              <div className="rounded-xl border border-dashed border-gray-300 p-8 text-center text-sm text-gray-500">
                Selecciona un patrón para ver su detalle.
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

function PatternDetail({ pattern }: { pattern: Pattern }) {
  return (
    <article className="space-y-4 rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
      <header>
        <h2 className="text-lg font-semibold text-gray-900">{pattern.pattern_name}</h2>
        {pattern.category && <p className="text-sm text-gray-500">{pattern.category}</p>}
      </header>
      <Section title="Descripción" text={pattern.description} />
      <Section title="Casos de uso" text={pattern.use_cases} />
      <Tradeoffs tradeoffs={pattern.tradeoffs} />
      <Section title="Cuándo no usarlo" text={pattern.when_not_to_use} />
      <SourceChunks patternId={pattern.id} />
    </article>
  )
}

function Section({ title, text }: { title: string; text: string | null }) {
  if (!text) return null
  return (
    <section>
      <h3 className="text-sm font-semibold text-gray-700">{title}</h3>
      <p className="mt-1 whitespace-pre-line text-sm text-gray-700">{text}</p>
    </section>
  )
}

const tradeoffStyle: Record<string, string> = {
  ventajas: 'text-emerald-700',
  desventajas: 'text-red-700',
}

function Tradeoffs({ tradeoffs }: { tradeoffs: Pattern['tradeoffs'] }) {
  const entries = Object.entries(tradeoffs ?? {})
  if (entries.length === 0) return null
  return (
    <section>
      <h3 className="text-sm font-semibold text-gray-700">Trade-offs</h3>
      <div className="mt-1 grid gap-3 sm:grid-cols-2">
        {entries.map(([key, value]) => (
          <div key={key}>
            <p className={`text-xs font-semibold uppercase ${tradeoffStyle[key.toLowerCase()] ?? 'text-gray-600'}`}>{key}</p>
            {Array.isArray(value) ? (
              <ul className="mt-1 list-disc space-y-1 pl-4 text-sm text-gray-700">
                {value.map((item, i) => <li key={i}>{String(item)}</li>)}
              </ul>
            ) : (
              <p className="mt-1 text-sm text-gray-700">{typeof value === 'string' ? value : JSON.stringify(value)}</p>
            )}
          </div>
        ))}
      </div>
    </section>
  )
}

function SourceChunks({ patternId }: { patternId: number }) {
  const [open, setOpen] = useState(false)
  const [chunks, setChunks] = useState<PatternSourceChunk[] | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    setOpen(false)
    setChunks(null)
    setError('')
  }, [patternId])

  useEffect(() => {
    if (!open || chunks !== null) return
    let cancelled = false
    setLoading(true)
    listPatternSourceChunks(patternId)
      .then((data) => { if (!cancelled) setChunks(data) })
      .catch((err) => { if (!cancelled) setError(err instanceof Error ? err.message : 'Error al cargar las fuentes') })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [open, chunks, patternId])

  return (
    <section className="border-t border-gray-100 pt-4">
      <button type="button" onClick={() => setOpen((v) => !v)} className="text-sm font-medium text-sky-700 hover:underline">
        {open ? 'Ocultar fuentes' : 'Ver fuentes documentales'}
      </button>
      {open && (
        <div className="mt-3 space-y-3">
          {loading && <p className="text-sm text-gray-500">Cargando fuentes...</p>}
          {error && <p className="text-sm text-red-700">{error}</p>}
          {chunks?.length === 0 && <p className="text-sm italic text-gray-400">No hay fuentes cargadas para este patrón.</p>}
          {chunks?.map((chunk) => (
            <div key={chunk.id} className="rounded-lg bg-slate-50 p-3">
              {chunk.chunk_metadata?.filename && (
                <p className="mb-1 text-xs font-medium text-gray-500">
                  {chunk.chunk_metadata.filename}
                  {chunk.chunk_metadata.source_type && ` · ${chunk.chunk_metadata.source_type.toUpperCase()}`}
                </p>
              )}
              <p className="max-h-48 overflow-y-auto whitespace-pre-line text-sm text-gray-700">{chunk.chunk_text}</p>
            </div>
          ))}
        </div>
      )}
    </section>
  )
}
