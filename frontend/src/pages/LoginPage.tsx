import { useState, FormEvent } from 'react'
import { Link, useNavigate, useLocation } from 'react-router-dom'
import { authStore } from '../stores/authStore'
import { AuthLayout } from '../components/AuthLayout'

export function LoginPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)

  const login = authStore((state) => state.login)
  const status = authStore((state) => state.status)

  const from = (location.state as { from?: string })?.from || '/projects'

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setError('')

    if (!username.trim() || !password.trim()) {
      setError('Please enter username and password')
      return
    }

    setIsSubmitting(true)
    try {
      await login(username, password)
      navigate(from, { replace: true })
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Login failed'
      setError(message)
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <AuthLayout
      title="Bienvenido de nuevo"
      subtitle="Ingresa tus credenciales para acceder a tu espacio de trabajo."
      greeting="¡Hola! Inicia sesión para comenzar."
    >
      <form className="space-y-5" onSubmit={handleSubmit}>
        <div>
          <label htmlFor="username" className="mb-1 block text-sm font-medium text-gray-700">
            Nombre de usuario
          </label>
          <div className="relative">
            <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-gray-400">
              <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
              </svg>
            </span>
            <input
              id="username"
              name="username"
              type="text"
              autoComplete="username"
              required
              className="block w-full rounded-xl border border-gray-200 bg-gray-50 py-3 pl-10 pr-3 text-gray-900 focus:border-[#0e54ce] focus:outline-none focus:ring-1 focus:ring-[#0e54ce]"
              placeholder="Nombre de usuario"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              disabled={isSubmitting}
            />
          </div>
        </div>

        <div>
          <label htmlFor="password" className="mb-1 block text-sm font-medium text-gray-700">
            Contraseña
          </label>
          <div className="relative">
            <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-gray-400">
              <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
              </svg>
            </span>
            <input
              id="password"
              name="password"
              type={showPassword ? 'text' : 'password'}
              autoComplete="current-password"
              required
              className="block w-full rounded-xl border border-gray-200 bg-gray-50 py-3 pl-10 pr-10 text-gray-900 focus:border-[#0e54ce] focus:outline-none focus:ring-1 focus:ring-[#0e54ce]"
              placeholder="Contraseña"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={isSubmitting}
            />
            <button
              type="button"
              onClick={() => setShowPassword(!showPassword)}
              tabIndex={-1}
              className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-gray-400 hover:text-gray-600"
              aria-label={showPassword ? 'Ocultar contraseña' : 'Mostrar contraseña'}
            >
              {showPassword ? (
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21" />
                </svg>
              ) : (
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                </svg>
              )}
            </button>
          </div>
        </div>

        {error && (
          <div className="text-red-600 text-sm text-center">{error}</div>
        )}

        <button
          type="submit"
          disabled={isSubmitting || status === 'loading'}
          className="w-full rounded-xl bg-[#0e54ce] py-3 text-base font-semibold text-white shadow-[0px_4px_14px_rgba(14,84,206,0.35)] transition-colors hover:bg-[#0b45ab] disabled:cursor-not-allowed disabled:opacity-50"
        >
          {isSubmitting ? 'Iniciando sesión...' : 'Iniciar sesión'}
        </button>
      </form>

      <p className="mt-6 text-center text-sm text-gray-600">
        ¿No tienes cuenta?{' '}
        <Link to="/register" className="font-medium text-[#0e54ce] hover:text-blue-700">
          Regístrate
        </Link>
      </p>
    </AuthLayout>
  )
}
