import { useEffect, useState } from 'react'
import bodyImg from '../assets/robot-body.webp'
import restArm from '../assets/rest-arm.webp'
import waveAArm from '../assets/wave-a-arm.webp'
import waveBArm from '../assets/wave-b-arm.webp'
import { ARM_STYLE, ROBOT_ASPECT_RATIO } from './robotLayout'

const SEQUENCE = [restArm, waveAArm, waveBArm, waveAArm, restArm]
const FRAME_MS = 260

// Con "reducir movimiento" el robot se muestra quieto, en la pose de reposo.
const prefersReducedMotion = () =>
  typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true

export function RobotGreeter() {
  const [reduceMotion] = useState(prefersReducedMotion)
  const [step, setStep] = useState(() => (reduceMotion ? SEQUENCE.length - 1 : 0))
  const [floating, setFloating] = useState(false)
  const current = SEQUENCE[step]

  useEffect(() => {
    if (reduceMotion) return
    if (step >= SEQUENCE.length - 1) {
      setFloating(true)
      return
    }
    const timer = setTimeout(() => setStep((s) => s + 1), FRAME_MS)
    return () => clearTimeout(timer)
  }, [step, reduceMotion])

  return (
    <div
      className={`relative w-40 select-none drop-shadow-[0_18px_24px_rgba(14,84,206,0.25)] sm:w-52 ${
        floating ? 'animate-robot-float' : ''
      }`}
      style={{ aspectRatio: ROBOT_ASPECT_RATIO }}
    >
      <img src={bodyImg} alt="Asistente robot de ArchAgent" draggable={false} loading="lazy" className="absolute inset-0 h-full w-full" />
      {[restArm, waveAArm, waveBArm].map((src) => (
        <img
          key={src}
          src={src}
          alt=""
          draggable={false}
          loading="lazy"
          className="absolute transition-opacity duration-150 ease-in-out"
          style={{ ...ARM_STYLE, opacity: current === src ? 1 : 0 }}
        />
      ))}
    </div>
  )
}
