import { useState } from 'react'
import type { Pattern, PatternImageSource } from '../api/patterns'

type PatternWithImage = Pick<Pattern, 'pattern_name' | 'image' | 'image_alt' | 'image_source'>

/** "autor · licencia", con ", adaptada" si la imagen se modificó (CC BY exige indicar los cambios). */
export function patternImageCredit(source?: PatternImageSource | null): string {
  if (!source) return ''
  const license = source.licencia ? `${source.licencia}${source.modificada ? ', adaptada' : ''}` : ''
  return [source.autor, license].filter(Boolean).join(' · ')
}

/** Texto alternativo de la imagen; si el YAML no lo trae, al menos nombra el patrón. */
export function patternImageAlt(pattern: PatternWithImage): string {
  return pattern.image_alt || `Diagrama ilustrativo de ${pattern.pattern_name}`
}

// Pie con la fuente enlazada, el autor y la licencia.
export function PatternImageCaption({ source }: { source?: PatternImageSource | null }) {
  if (!source) return null
  const credit = patternImageCredit(source)
  return (
    <figcaption className="mt-1 text-xs text-gray-500">
      Fuente:{' '}
      {source.url ? (
        <a href={source.url} target="_blank" rel="noreferrer" className="text-sky-700 hover:underline">
          {source.titulo || source.url}
        </a>
      ) : (
        source.titulo
      )}
      {credit && ` — ${credit}`}
    </figcaption>
  )
}

/**
 * Imagen ilustrativa de un patrón con su atribución. Si falta o no carga se
 * muestra un aviso en su lugar: lo que la rodea sigue funcionando.
 *
 * Quien la usa debe darle `key` con el patrón: así el aviso de "no se pudo
 * cargar" no se arrastra al cambiar de patrón.
 */
export function PatternFigure({ pattern, className = 'max-h-64 md:max-h-96' }: { pattern: PatternWithImage; className?: string }) {
  const [failed, setFailed] = useState(false)

  if (!pattern.image || failed) {
    return (
      <p role="status" className="mt-2 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800">
        {pattern.image
          ? 'No se pudo cargar la imagen de este patrón.'
          : 'Este patrón todavía no tiene una imagen ilustrativa.'}
      </p>
    )
  }
  return (
    <figure className="mt-2">
      {/* Fondo blanco fijo (no bg-white, que el modo oscuro oscurece): los diagramas son de fondo claro. */}
      <a href={pattern.image} target="_blank" rel="noreferrer" title="Abrir la imagen en una pestaña nueva"
        className="block overflow-hidden rounded-lg border border-gray-200 bg-[#ffffff] p-2">
        <img
          src={pattern.image}
          alt={patternImageAlt(pattern)}
          loading="lazy"
          onError={() => setFailed(true)}
          className={`mx-auto w-full object-contain ${className}`}
        />
      </a>
      <PatternImageCaption source={pattern.image_source} />
    </figure>
  )
}

/** Miniatura sin pie ni aviso: si no hay imagen o no carga, no ocupa lugar. */
export function PatternThumbnail({ pattern }: { pattern: PatternWithImage }) {
  const [failed, setFailed] = useState(false)
  if (!pattern.image || failed) return null
  return (
    <a href={pattern.image} target="_blank" rel="noreferrer" title={`Abrir la imagen de ${pattern.pattern_name} en una pestaña nueva`}
      className="mr-2 inline-block shrink-0 overflow-hidden rounded border border-gray-200 bg-[#ffffff] align-middle">
      {/* Alt corto: la descripción completa ya está en la imagen del patrón seleccionado. */}
      <img src={pattern.image} alt={`Miniatura de ${pattern.pattern_name}`} loading="lazy" onError={() => setFailed(true)}
        className="h-10 w-16 object-contain" />
    </a>
  )
}
