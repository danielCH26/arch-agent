import { type RefObject, useEffect, useRef } from 'react'

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

interface UseDialogOptions {
  open: boolean
  onClose: () => void
  // Elemento que recibe el foco al abrir; por defecto, el primero enfocable.
  initialFocusRef?: RefObject<HTMLElement>
  // Mientras es true, Esc no cierra (p. ej. durante un guardado).
  preventClose?: boolean
}

/**
 * Comportamiento accesible de un diálogo modal: foco inicial dentro del
 * diálogo, Tab/Shift+Tab atrapados en él, Esc para cerrar y devolución del
 * foco al elemento que lo abrió. Devuelve la ref del contenedor del diálogo.
 */
export function useDialog<T extends HTMLElement = HTMLDivElement>({
  open,
  onClose,
  initialFocusRef,
  preventClose = false,
}: UseDialogOptions): RefObject<T> {
  const containerRef = useRef<T>(null)
  // Refs para no reinstalar los listeners en cada render.
  const onCloseRef = useRef(onClose)
  const preventCloseRef = useRef(preventClose)
  onCloseRef.current = onClose
  preventCloseRef.current = preventClose

  useEffect(() => {
    if (!open) return
    const previouslyFocused = document.activeElement as HTMLElement | null
    const container = containerRef.current

    const focusables = () =>
      container ? Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE)) : []

    ;(initialFocusRef?.current ?? focusables()[0] ?? container)?.focus()

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        if (!preventCloseRef.current) {
          event.stopPropagation()
          onCloseRef.current()
        }
        return
      }
      if (event.key !== 'Tab' || !container) return
      const items = focusables()
      if (items.length === 0) {
        event.preventDefault()
        return
      }
      const first = items[0]
      const last = items[items.length - 1]
      const active = document.activeElement
      if (event.shiftKey && (active === first || !container.contains(active))) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && (active === last || !container.contains(active))) {
        event.preventDefault()
        first.focus()
      }
    }

    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      // Devolver el foco a quien abrió el diálogo, si sigue en la página.
      if (previouslyFocused && document.contains(previouslyFocused)) previouslyFocused.focus()
    }
  }, [open, initialFocusRef])

  return containerRef
}
