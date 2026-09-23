import { useEffect, useState } from 'react'
import bodyImg from '../assets/robot-body.png'
import restArm from '../assets/rest-arm.png'
import waveAArm from '../assets/wave-a-arm.png'
import waveBArm from '../assets/wave-b-arm.png'

// Posición del recorte del brazo/mano sobre el cuerpo (robot-body.png, 1129x970).
// El cuerpo tiene ese hueco siempre transparente: la capa de brazo (una de las tres)
// lo cubre por completo en todo momento, así nunca se asoma un brazo "fantasma" detrás.
const ARM_STYLE = {
  left: '62.0%',
  top: '19.6%',
  width: '32.8%',
  height: '32.0%',
}

const SEQUENCE = [restArm, waveAArm, waveBArm, waveAArm, restArm]
const FRAME_MS = 260

export function RobotGreeter() {
  const [step, setStep] = useState(0)
  const [floating, setFloating] = useState(false)
  const current = SEQUENCE[step]

  useEffect(() => {
    if (step >= SEQUENCE.length - 1) {
      setFloating(true)
      return
    }
    const timer = setTimeout(() => setStep((s) => s + 1), FRAME_MS)
    return () => clearTimeout(timer)
  }, [step])

  return (
    <div
      className={`relative w-40 select-none drop-shadow-[0_18px_24px_rgba(14,84,206,0.25)] sm:w-52 ${
        floating ? 'animate-robot-float' : ''
      }`}
      style={{ aspectRatio: '1129 / 970' }}
    >
      <img src={bodyImg} alt="Asistente robot de ArqAgent" draggable={false} className="absolute inset-0 h-full w-full" />
      {[restArm, waveAArm, waveBArm].map((src) => (
        <img
          key={src}
          src={src}
          alt=""
          draggable={false}
          className="absolute transition-opacity duration-150 ease-in-out"
          style={{ ...ARM_STYLE, opacity: current === src ? 1 : 0 }}
        />
      ))}
    </div>
  )
}
