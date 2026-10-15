import robotImg from '../assets/robot-avatar.webp'

interface LogoProps {
  // Alto en px; el ancho sigue la proporción de la imagen del robot.
  size?: number
  className?: string
  // Vacío cuando el logo va junto al texto "ArchAgent" (evita repetirlo).
  alt?: string
}

export function Logo({ size = 64, className = '', alt = 'ArchAgent' }: LogoProps) {
  return (
    <img
      src={robotImg}
      alt={alt}
      draggable={false}
      className={`w-auto select-none ${className}`}
      style={{ height: size }}
    />
  )
}
