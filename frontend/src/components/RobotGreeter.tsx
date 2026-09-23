import { useState } from 'react'
import bodyImg from '../assets/robot-body.png'
import armImg from '../assets/robot-arm.png'

// Posición del sprite del brazo dentro del cuerpo, como % del recorte original
// (robot-assistant original: 1139x980, brazo recortado en 680,255 - 1050,580).
// transformOrigin ubicado sobre la rótula del hombro para que el brazo pivote ahí.
const ARM_STYLE = {
  left: '59.70%',
  top: '26.02%',
  width: '32.48%',
  height: '33.16%',
  transformOrigin: '14.9% 53.8%',
}

export function RobotGreeter() {
  const [phase, setPhase] = useState<'greet' | 'float'>('greet')

  return (
    <div
      className={`relative w-40 select-none drop-shadow-[0_18px_24px_rgba(14,84,206,0.25)] sm:w-52 ${
        phase === 'float' ? 'animate-robot-float' : ''
      }`}
      style={{ aspectRatio: '1139 / 980' }}
    >
      <img src={bodyImg} alt="Asistente robot de ArqAgent" draggable={false} className="absolute inset-0 h-full w-full" />
      <img
        src={armImg}
        alt=""
        draggable={false}
        onAnimationEnd={() => {
          if (phase === 'greet') setPhase('float')
        }}
        className={`absolute ${phase === 'greet' ? 'animate-arm-wave' : ''}`}
        style={ARM_STYLE}
      />
    </div>
  )
}
