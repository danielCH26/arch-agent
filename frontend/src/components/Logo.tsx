import robotImg from '../assets/robot-avatar.png'

interface LogoProps {
  // Alto en px; el ancho sigue la proporción de la imagen del robot.
  size?: number
  className?: string
}

export function Logo({ size = 64, className = '' }: LogoProps) {
  return (
    <img
      src={robotImg}
      alt="ArchAgent"
      draggable={false}
      className={`w-auto select-none ${className}`}
      style={{ height: size }}
    />
  )
}
