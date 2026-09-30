import { Component, type ErrorInfo, type ReactNode } from 'react'
import robotAvatar from '../assets/robot-avatar.png'

interface ErrorBoundaryProps {
  children: ReactNode
  // Al cambiar (p. ej. la ruta actual) se descarta el error y se vuelve a
  // intentar renderizar el contenido.
  resetKey?: unknown
  // `page`: ocupa el área de contenido (el menú sigue disponible).
  // `app`: pantalla completa, para errores fuera del Layout.
  variant?: 'page' | 'app'
}

interface ErrorBoundaryState {
  error: Error | null
}

/**
 * Evita la pantalla en blanco cuando un componente lanza un error al
 * renderizar: muestra un mensaje amigable con opciones para recuperarse.
 */
export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Error de renderizado:', error, info.componentStack)
  }

  componentDidUpdate(prevProps: ErrorBoundaryProps) {
    if (this.state.error && prevProps.resetKey !== this.props.resetKey) {
      this.setState({ error: null })
    }
  }

  render() {
    if (!this.state.error) return this.props.children

    const fullScreen = this.props.variant === 'app'

    return (
      <div
        role="alert"
        className={`flex flex-col items-center justify-center px-4 text-center ${
          fullScreen ? 'min-h-dvh bg-gray-100' : 'py-16'
        }`}
      >
        <img src={robotAvatar} alt="" aria-hidden="true" draggable={false} className="h-20 w-auto select-none" />
        <h1 className="mt-4 font-display text-2xl font-semibold text-gray-900">Algo salió mal</h1>
        <p className="mt-2 max-w-md text-gray-600">
          No pudimos mostrar esta sección. Tu información está a salvo; intenta de nuevo o vuelve a tus proyectos.
        </p>
        <div className="mt-6 flex flex-wrap justify-center gap-3">
          <button
            type="button"
            onClick={() => this.setState({ error: null })}
            className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
          >
            Intentar de nuevo
          </button>
          <a
            href="/projects"
            className="rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
          >
            Ir a mis proyectos
          </a>
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="rounded-lg px-4 py-2 text-sm font-medium text-gray-600 hover:bg-gray-200"
          >
            Recargar página
          </button>
        </div>
      </div>
    )
  }
}
