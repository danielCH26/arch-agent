interface IconProps {
  className?: string
}

interface OutlineIconProps extends IconProps {
  d: string
  viewBox?: string
  strokeWidth?: number
}

function OutlineIcon({ className = 'h-5 w-5', d, viewBox = '0 0 24 24', strokeWidth = 1.5 }: OutlineIconProps) {
  return (
    <svg aria-hidden="true" className={`shrink-0 ${className}`} fill="none" stroke="currentColor" viewBox={viewBox}>
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={strokeWidth} d={d} />
    </svg>
  )
}

// Íconos del mockup de Figma (viewBox y trazo originales).
export const ClockIcon = (p: IconProps) => (
  <OutlineIcon
    {...p}
    viewBox="0 0 31 32"
    strokeWidth={3.5}
    d="M15.5002 7.99999V16L20.6668 18.6667M28.4168 16C28.4168 23.3638 22.6338 29.3333 15.5002 29.3333C8.36648 29.3333 2.5835 23.3638 2.5835 16C2.5835 8.63619 8.36648 2.66666 15.5002 2.66666C22.6338 2.66666 28.4168 8.63619 28.4168 16Z"
  />
)

export const ChatIcon = (p: IconProps) => (
  <OutlineIcon
    {...p}
    viewBox="0 0 33 32"
    strokeWidth={4}
    d="M28.875 20C28.875 20.7072 28.5853 21.3855 28.0695 21.8856C27.5538 22.3857 26.8543 22.6667 26.125 22.6667H9.625L4.125 28V6.66667C4.125 5.95942 4.41473 5.28115 4.93046 4.78105C5.44618 4.28095 6.14565 4 6.875 4H26.125C26.8543 4 27.5538 4.28095 28.0695 4.78105C28.5853 5.28115 28.875 5.95942 28.875 6.66667V20Z"
  />
)

export const ArchiveIcon = (p: IconProps) => (
  <OutlineIcon
    {...p}
    viewBox="0 0 28 31"
    strokeWidth={3.5}
    d="M24.5 6.45834C24.5 8.59845 19.799 10.3333 14 10.3333C8.20101 10.3333 3.5 8.59845 3.5 6.45834M24.5 6.45834C24.5 4.31824 19.799 2.58334 14 2.58334C8.20101 2.58334 3.5 4.31824 3.5 6.45834M24.5 6.45834V24.5417C24.5 26.6858 19.8333 28.4167 14 28.4167C8.16667 28.4167 3.5 26.6858 3.5 24.5417V6.45834M24.5 15.5C24.5 17.6442 19.8333 19.375 14 19.375C8.16667 19.375 3.5 17.6442 3.5 15.5"
  />
)

export const DocumentIcon = (p: IconProps) => (
  <OutlineIcon
    {...p}
    d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z"
  />
)
