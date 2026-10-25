import { act, render } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { RobotGreeter } from '../RobotGreeter'
import { setMediaMatches } from '../../test/setup'

// Capas de brazo visibles (opacity 1) en el orden reposo, saludo A, saludo B.
const visibleArms = (container: HTMLElement) =>
  [...container.querySelectorAll<HTMLImageElement>('img[alt=""]')].map((img) => img.style.opacity)

describe('RobotGreeter', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('saluda (cambia de brazo) con las animaciones activas', () => {
    const { container } = render(<RobotGreeter />)
    expect(visibleArms(container)).toEqual(['1', '0', '0'])
    act(() => {
      vi.advanceTimersByTime(260)
    })
    expect(visibleArms(container)).toEqual(['0', '1', '0'])
  })

  it('con movimiento reducido se queda en la pose de reposo', () => {
    setMediaMatches({ '(prefers-reduced-motion: reduce)': true })
    const { container } = render(<RobotGreeter />)
    act(() => {
      vi.advanceTimersByTime(2000)
    })
    expect(visibleArms(container)).toEqual(['1', '0', '0'])
    expect(container.firstElementChild).not.toHaveClass('animate-robot-float')
  })
})
