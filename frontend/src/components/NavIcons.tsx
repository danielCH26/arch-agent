import type { DiagramDecision } from '../api/diagrams'

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

// Íconos del mockup de Figma (viewBox original). El trazo se escala para
// equivaler a 1.5 en un viewBox de 24 y que todos se vean del mismo grosor.
// Carpeta (Heroicons outline), para "Mis proyectos".
export const FolderIcon = (p: IconProps) => (
  <OutlineIcon
    {...p}
    d="M2.25 12.75V12A2.25 2.25 0 014.5 9.75h15A2.25 2.25 0 0121.75 12v.75m-8.69-6.44l-2.12-2.12a1.5 1.5 0 00-1.061-.44H4.5A2.25 2.25 0 002.25 6v12a2.25 2.25 0 002.25 2.25h15A2.25 2.25 0 0021.75 18V9a2.25 2.25 0 00-2.25-2.25h-5.379a1.5 1.5 0 01-1.06-.44z"
  />
)

export const ClockIcon = (p: IconProps) => (
  <OutlineIcon
    {...p}
    viewBox="0 0 31 32"
    strokeWidth={2}
    d="M15.5002 7.99999V16L20.6668 18.6667M28.4168 16C28.4168 23.3638 22.6338 29.3333 15.5002 29.3333C8.36648 29.3333 2.5835 23.3638 2.5835 16C2.5835 8.63619 8.36648 2.66666 15.5002 2.66666C22.6338 2.66666 28.4168 8.63619 28.4168 16Z"
  />
)

export const ChatIcon = (p: IconProps) => (
  <OutlineIcon
    {...p}
    viewBox="0 0 33 32"
    strokeWidth={2}
    d="M28.875 20C28.875 20.7072 28.5853 21.3855 28.0695 21.8856C27.5538 22.3857 26.8543 22.6667 26.125 22.6667H9.625L4.125 28V6.66667C4.125 5.95942 4.41473 5.28115 4.93046 4.78105C5.44618 4.28095 6.14565 4 6.875 4H26.125C26.8543 4 27.5538 4.28095 28.0695 4.78105C28.5853 5.28115 28.875 5.95942 28.875 6.66667V20Z"
  />
)

export const ArchiveIcon = (p: IconProps) => (
  <OutlineIcon
    {...p}
    viewBox="0 0 28 31"
    strokeWidth={1.9}
    d="M24.5 6.45834C24.5 8.59845 19.799 10.3333 14 10.3333C8.20101 10.3333 3.5 8.59845 3.5 6.45834M24.5 6.45834C24.5 4.31824 19.799 2.58334 14 2.58334C8.20101 2.58334 3.5 4.31824 3.5 6.45834M24.5 6.45834V24.5417C24.5 26.6858 19.8333 28.4167 14 28.4167C8.16667 28.4167 3.5 26.6858 3.5 24.5417V6.45834M24.5 15.5C24.5 17.6442 19.8333 19.375 14 19.375C8.16667 19.375 3.5 17.6442 3.5 15.5"
  />
)

export const DocumentIcon = (p: IconProps) => (
  <OutlineIcon
    {...p}
    d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z"
  />
)

export const PlusIcon = (p: IconProps) => <OutlineIcon {...p} d="M12 4.5v15m7.5-7.5h-15" />

// Decisiones sobre un diagrama: las mismas en el chat y en el historial.
const decisionPaths: Record<DiagramDecision, string> = {
  approve: 'M4.5 12.75l6 6 9-13.5',
  reject: 'M6 18L18 6M6 6l12 12',
  modify: 'M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L6.832 19.82a4.5 4.5 0 01-1.897 1.13l-2.685.8.8-2.685a4.5 4.5 0 011.13-1.897L16.863 4.487z',
}

export const DecisionIcon = ({ decision, className = 'h-3.5 w-3.5' }: IconProps & { decision: DiagramDecision }) => (
  <OutlineIcon className={className} strokeWidth={2} d={decisionPaths[decision]} />
)

export const WarningIcon = ({ className = 'h-4 w-4' }: IconProps) => (
  <OutlineIcon
    className={className}
    d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z"
  />
)

export const InfoIcon = ({ className = 'h-4 w-4' }: IconProps) => (
  <OutlineIcon
    className={className}
    d="M11.25 11.25l.041-.02a.75.75 0 011.063.852l-.708 2.836a.75.75 0 001.063.853l.041-.021M21 12a9 9 0 11-18 0 9 9 0 0118 0zm-9-3.75h.008v.008H12V8.25z"
  />
)

// Fase completada / ADR aprobado (Heroicons check-circle outline).
export const CheckCircleIcon = ({ className = 'h-4 w-4' }: IconProps) => (
  <OutlineIcon className={className} d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
)

// Celebración al cerrar el proyecto (Heroicons sparkles outline).
export const SparklesIcon = ({ className = 'h-5 w-5' }: IconProps) => (
  <OutlineIcon
    className={className}
    d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.456 2.456L21.75 6l-1.035.259a3.375 3.375 0 00-2.456 2.456z"
  />
)

export const CheckIcon = ({ className = 'h-4 w-4' }: IconProps) => (
  <OutlineIcon className={className} strokeWidth={2} d={decisionPaths.approve} />
)
