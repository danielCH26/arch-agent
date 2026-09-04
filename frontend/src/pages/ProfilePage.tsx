import { useEffect, useState, type FormEvent } from 'react'
import { changeUserPassword, getUserProfile, updateUserProfile, UserProfile } from '../api/users'
import { authStore } from '../stores/authStore'

const usernamePattern = /^[a-zA-Z0-9_]{3,100}$/

function validatePassword(password: string): string | null {
  if (password.length < 8) return 'La contraseña debe tener al menos 8 caracteres.'
  if (!/[A-Z]/.test(password)) return 'La contraseña debe incluir al menos una letra mayúscula.'
  if (!/[0-9]/.test(password)) return 'La contraseña debe incluir al menos un número.'
  if (!/[!@#$%^&*()_+\-=[\]{};':"\\|,.<>/?]/.test(password)) {
    return 'La contraseña debe incluir al menos un carácter especial.'
  }
  return null
}

export function ProfilePage() {
  const [profile, setProfile] = useState<UserProfile | null>(null)
  const updateAuthUser = authStore((state) => state.updateUser)
  const [username, setUsername] = useState('')
  const [email, setEmail] = useState('')
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [showCurrentPassword, setShowCurrentPassword] = useState(false)
  const [showNewPassword, setShowNewPassword] = useState(false)
  const [loading, setLoading] = useState(true)
  const [savingProfile, setSavingProfile] = useState(false)
  const [savingPassword, setSavingPassword] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [profileMessage, setProfileMessage] = useState<string | null>(null)
  const [passwordMessage, setPasswordMessage] = useState<string | null>(null)
  const [profileFormError, setProfileFormError] = useState<string | null>(null)
  const [passwordFormError, setPasswordFormError] = useState<string | null>(null)

  useEffect(() => {
    getUserProfile()
      .then((p) => {
        setProfile(p)
        setUsername(p.username)
        setEmail(p.email)
      })
      .catch((err) => {
        console.error('ProfilePage error:', err)
        setError('Error al cargar el perfil')
      })
      .finally(() => setLoading(false))
  }, [])

  const hasProfileChanges = profile
    ? username.trim() !== profile.username || email.trim() !== profile.email
    : false

  const validateProfileForm = () => {
    const nextUsername = username.trim()
    const nextEmail = email.trim()

    if (!usernamePattern.test(nextUsername)) {
      return 'El username debe tener entre 3 y 100 caracteres: letras, números o guion bajo.'
    }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(nextEmail)) {
      return 'El email no tiene un formato válido.'
    }
    return null
  }

  const handleProfileSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setProfileMessage(null)
    setProfileFormError(null)

    const validationError = validateProfileForm()
    if (validationError) {
      setProfileFormError(validationError)
      return
    }

    setSavingProfile(true)
    try {
      const updated = await updateUserProfile({
        username: username.trim(),
        email: email.trim(),
      })
      setProfile(updated)
      setUsername(updated.username)
      setEmail(updated.email)
      updateAuthUser({ username: updated.username, email: updated.email })
      setProfileMessage('Perfil actualizado correctamente.')
    } catch (err) {
      setProfileFormError(err instanceof Error ? err.message : 'No se pudo actualizar el perfil.')
    } finally {
      setSavingProfile(false)
    }
  }

  const handlePasswordSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setPasswordMessage(null)
    setPasswordFormError(null)

    if (!currentPassword) {
      setPasswordFormError('Ingresa tu contraseña actual.')
      return
    }

    const validationError = validatePassword(newPassword)
    if (validationError) {
      setPasswordFormError(validationError)
      return
    }

    setSavingPassword(true)
    try {
      await changeUserPassword({
        current_password: currentPassword,
        new_password: newPassword,
      })
      setCurrentPassword('')
      setNewPassword('')
      setPasswordMessage('Contraseña actualizada correctamente.')
    } catch (err) {
      setPasswordFormError(err instanceof Error ? err.message : 'No se pudo cambiar la contraseña.')
    } finally {
      setSavingPassword(false)
    }
  }

  if (loading) {
    return (
      <div className="flex justify-center py-12">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
      </div>
    )
  }

  if (error || !profile) {
    return (
      <div className="p-4 bg-red-50 text-red-700 rounded-lg">
        {error || 'No se pudo cargar el perfil'}
      </div>
    )
  }

  return (
    <div className="max-w-2xl">
      <h1 className="text-2xl font-bold text-gray-900 mb-6">Mi Perfil</h1>

      <form
        onSubmit={handleProfileSubmit}
        className="bg-white rounded-lg shadow-sm border border-gray-200 p-6 space-y-4"
      >
        <div>
          <label htmlFor="username" className="block text-sm font-medium text-gray-700 mb-1">
            Nombre de usuario
          </label>
          <input
            id="username"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-gray-900 focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-100"
            autoComplete="username"
          />
        </div>

        <div>
          <label htmlFor="email" className="block text-sm font-medium text-gray-700 mb-1">
            Correo electrónico
          </label>
          <input
            id="email"
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-gray-900 focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-100"
            autoComplete="email"
          />
        </div>

        {profile.created_at && (
          <div>
            <span className="text-sm font-medium text-gray-500">Miembro desde</span>
            <p className="text-gray-900">
              {new Date(profile.created_at).toLocaleDateString('es-ES', {
                year: 'numeric',
                month: 'long',
                day: 'numeric',
              })}
            </p>
          </div>
        )}

        {profileFormError && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
            {profileFormError}
          </div>
        )}

        {profileMessage && (
          <div className="rounded-lg border border-green-200 bg-green-50 px-3 py-2 text-sm text-green-700">
            {profileMessage}
          </div>
        )}

        <button
          type="submit"
          disabled={!hasProfileChanges || savingProfile}
          className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-indigo-700 disabled:cursor-not-allowed disabled:bg-gray-300"
        >
          {savingProfile ? 'Guardando...' : 'Guardar cambios'}
        </button>
      </form>

      <form
        onSubmit={handlePasswordSubmit}
        className="mt-6 bg-white rounded-lg shadow-sm border border-gray-200 p-6 space-y-4"
      >
        <h2 className="text-lg font-semibold text-gray-900">Cambiar contraseña</h2>

        <div>
          <label htmlFor="current-password" className="block text-sm font-medium text-gray-700 mb-1">
            Contraseña actual
          </label>
          <div className="relative">
            <input
              id="current-password"
              type={showCurrentPassword ? 'text' : 'password'}
              value={currentPassword}
              onChange={(event) => setCurrentPassword(event.target.value)}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 pr-10 text-gray-900 focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-100"
              autoComplete="current-password"
            />
            <button
              type="button"
              onClick={() => setShowCurrentPassword(!showCurrentPassword)}
              tabIndex={-1}
              className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-gray-400 hover:text-gray-600"
              aria-label={showCurrentPassword ? 'Ocultar contraseña actual' : 'Mostrar contraseña actual'}
            >
              {showCurrentPassword ? (
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21" />
                </svg>
              ) : (
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268-2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                </svg>
              )}
            </button>
          </div>
        </div>

        <div>
          <label htmlFor="new-password" className="block text-sm font-medium text-gray-700 mb-1">
            Nueva contraseña
          </label>
          <div className="relative">
            <input
              id="new-password"
              type={showNewPassword ? 'text' : 'password'}
              value={newPassword}
              onChange={(event) => setNewPassword(event.target.value)}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 pr-10 text-gray-900 focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-100"
              autoComplete="new-password"
            />
            <button
              type="button"
              onClick={() => setShowNewPassword(!showNewPassword)}
              tabIndex={-1}
              className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-gray-400 hover:text-gray-600"
              aria-label={showNewPassword ? 'Ocultar nueva contraseña' : 'Mostrar nueva contraseña'}
            >
              {showNewPassword ? (
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21" />
                </svg>
              ) : (
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268-2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                </svg>
              )}
            </button>
          </div>
        </div>

        {passwordFormError && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
            {passwordFormError}
          </div>
        )}

        {passwordMessage && (
          <div className="rounded-lg border border-green-200 bg-green-50 px-3 py-2 text-sm text-green-700">
            {passwordMessage}
          </div>
        )}

        <button
          type="submit"
          disabled={savingPassword}
          className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-indigo-700 disabled:cursor-not-allowed disabled:bg-gray-300"
        >
          {savingPassword ? 'Guardando...' : 'Cambiar contraseña'}
        </button>
      </form>
    </div>
  )
}
