import { ReactNode } from 'react'
import { RobotGreeter } from './RobotGreeter'

interface AuthLayoutProps {
  title: ReactNode
  subtitle: string
  greeting: string
  children: ReactNode
}

// Patrón de circuito tipo "tech" tileable, codificado como SVG inline.
const CIRCUIT_PATTERN =
  "data:image/svg+xml;utf8," +
  encodeURIComponent(`
    <svg xmlns="http://www.w3.org/2000/svg" width="160" height="160" viewBox="0 0 160 160">
      <g fill="none" stroke="#0e54ce" stroke-width="1" opacity="0.35">
        <path d="M0 40 H50 V10 H90" />
        <path d="M160 60 H110 V90 H70 V130" />
        <path d="M0 120 H30 V150" />
        <path d="M130 0 V30 H160" />
        <path d="M40 160 V140 H90 V100" />
        <circle cx="50" cy="40" r="3" />
        <circle cx="90" cy="10" r="3" />
        <circle cx="110" cy="60" r="3" />
        <circle cx="70" cy="90" r="3" />
        <circle cx="30" cy="120" r="3" />
        <circle cx="130" cy="30" r="3" />
        <circle cx="90" cy="140" r="3" />
      </g>
    </svg>
  `)

export function AuthLayout({ title, subtitle, greeting, children }: AuthLayoutProps) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-[#e4f2fa] to-[#f7fbf9] px-4 py-12">
      <div className="grid w-full max-w-5xl grid-cols-1 gap-6 md:grid-cols-2">
        <div className="flex flex-col justify-center rounded-3xl bg-white p-8 shadow-[0px_10px_40px_rgba(14,84,206,0.12)] sm:p-12">
          <span className="mb-6 text-xl font-semibold text-gray-900">
            Arq<span className="text-[#0e54ce]">Agent</span>
          </span>

          <h1 className="text-3xl font-bold text-gray-900 sm:text-4xl">{title}</h1>
          <p className="mt-2 text-sm text-gray-500">{subtitle}</p>

          <div className="mt-8">{children}</div>
        </div>

        <div className="relative hidden flex-col items-center overflow-hidden rounded-3xl bg-gradient-to-br from-[#cdeaf5] to-[#e3f7ef] p-6 pt-10 shadow-[0px_10px_40px_rgba(14,84,206,0.12)] sm:p-8 sm:pt-12 md:flex">
          <div
            className="pointer-events-none absolute inset-0"
            style={{
              backgroundImage: `url("${CIRCUIT_PATTERN}")`,
              backgroundSize: '160px 160px',
            }}
          />

          <h2 className="relative z-10 w-full text-center text-3xl font-bold leading-tight text-gray-900">
            Tu asistente de ingeniería de software,
            <br />
            listo para ayudar
          </h2>

          <div className="relative z-10 mt-14 flex w-full flex-1 items-end justify-center pb-4">
            <div className="relative">
              <div className="absolute -right-4 -top-16 max-w-[160px] rounded-2xl rounded-bl-sm bg-white px-4 py-3 text-sm text-gray-700 shadow-[0px_6px_20px_rgba(0,0,0,0.12)] sm:-right-8 sm:-top-20">
                {greeting}
              </div>
              <RobotGreeter />
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
