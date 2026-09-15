import logoImg from '../assets/arqagent-logo.png'

interface LogoProps {
  size?: number
  className?: string
}

export function Logo({ size = 64, className = '' }: LogoProps) {
  return (
    <img
      src={logoImg}
      alt="ArqAgent"
      width={size}
      height={size}
      className={className}
      style={{ width: size, height: size }}
    />
  )
}
