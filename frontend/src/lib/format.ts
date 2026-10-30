// Formatos comunes para toda la interfaz (fechas y nombres de proyecto).
const LOCALE = 'es-CO'

/** Fecha corta, p. ej. "2 oct 2026". */
export function formatDate(value: string | Date): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleDateString(LOCALE, { year: 'numeric', month: 'short', day: 'numeric' })
}

/** Fecha y hora, p. ej. "2 oct 2026, 3:45 p. m.". */
export function formatDateTime(value: string | Date): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleString(LOCALE, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}

// Siglas que van siempre en mayúsculas al mostrar el nombre de un proyecto.
// Mismas que DISPLAY_ACRONYMS de app/core/adr_generator.py.
const DISPLAY_ACRONYMS = new Set(['adr', 'api', 'ia', 'ai', 'erp', 'crm', 'mvp', 'saas', 'iot', 'ui', 'ux'])

/** Nombre del proyecto con mayúscula inicial y siglas en mayúsculas ("prueba adr" -> "Prueba ADR"). */
export function displayProjectName(name: string): string {
  const text = name
    .trim()
    .replace(/[\p{L}\p{N}]+/gu, (word) => (DISPLAY_ACRONYMS.has(word.toLowerCase()) ? word.toUpperCase() : word))
  return text.charAt(0).toUpperCase() + text.slice(1)
}
