// Formatos de fecha comunes para toda la interfaz.
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
