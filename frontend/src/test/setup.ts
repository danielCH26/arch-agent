import '@testing-library/jest-dom'
import { afterEach, vi } from 'vitest'

// jsdom no implementa matchMedia ni scrollIntoView. `setMediaMatches`
// permite simular preferencias del sistema en un test, p. ej.
// setMediaMatches({ '(prefers-reduced-motion: reduce)': true }).
let mediaMatches: Record<string, boolean> = {}

export function setMediaMatches(matches: Record<string, boolean>) {
  mediaMatches = matches
}

Object.defineProperty(window, 'matchMedia', {
  writable: true,
  configurable: true,
  value: vi.fn((query: string) => ({
    matches: mediaMatches[query] ?? false,
    media: query,
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
})

Element.prototype.scrollIntoView = vi.fn()

afterEach(() => {
  mediaMatches = {}
})
