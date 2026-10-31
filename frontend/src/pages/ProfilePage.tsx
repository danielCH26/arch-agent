import { useEffect, useState, type FormEvent } from 'react'
import { changeUserPassword, getUserProfile, updateUserProfile, UserProfile } from '../api/users'
import { PageHeader } from '../components/PageHeader'
import { formatDate } from '../lib/format'
import { authStore } from '../stores/authStore'

const usernamePattern = /^[a-zA-Z0-9_]{3,100}$/

const SECTION_TITLE = 'text-lg font-semibold text-gray-900'
const LABEL = 'mb-1 block text-sm font-medium text-gray-700'
const INPUT =
  'w-full rounded border border-gray-400 bg-gray-100 px-3 py-2.5 text-gray-900 focus:border-blue-600 focus:outline-none focus:ring-1 focus:ring-blue-600'

const EYE_OFF_PATH =
  'M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21'
const EYE_PATHS = [
  'M15 12a3 3 0 11-6 0 3 3 0 016 0z',
  'M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z',
]

interface PasswordFieldProps {
  id: string
  label: string
  value: string
  onChange: (value: string) => void
  autoComplete: string
}

/** Campo de contraseña con botón para mostrar u ocultar el texto. */
function PasswordField({ id, label, value, onChange, autoComplete }: PasswordFieldProps) {
  const [visible, setVisible] = useState(false)
  return (
    <div>
      <label htmlFor={id} className={LABEL}>
        {label}
      </label>
      <div className="relative">
        <input
          id={id}
          type={visible ? 'text' : 'password'}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          className={`${INPUT} pr-10`}
          autoComplete={autoComplete}
        />
        <button
          type="button"
          onClick={() => setVisible(!visible)}
          className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-gray-500 hover:bg-gray-100 hover:text-gray-800"
          aria-label={`Mostrar texto de «${label}»`}
          aria-pressed={visible}
        >
          <svg aria-hidden="true" className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            {(visible ? [EYE_OFF_PATH] : EYE_PATHS).map((d) => (
              <path key={d} strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d={d} />
            ))}
          </svg>
        </button>
      </div>
    </div>
  )
}

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
  const [confirmPassword, setConfirmPassword] = useState('')
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

  const hasPasswordInput = Boolean(currentPassword || newPassword || confirmPassword)
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
    if (newPassword !== confirmPassword) {
      setPasswordFormError('Las contraseñas no coinciden.')
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
      setConfirmPassword('')
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
    <div className="mx-auto max-w-4xl">
      <PageHeader title="Perfil" subtitle="Gestiona tus datos y tu contraseña." />

      <div className="mb-8 flex flex-col items-center gap-2">
        <div className="flex h-28 w-28 items-center justify-center rounded-full bg-blue-300 dark:bg-slate-600">
          <svg className="h-14 w-14 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M15.75 6a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0zM4.501 20.118a7.5 7.5 0 0114.998 0A17.933 17.933 0 0112 21.75c-2.676 0-5.216-.584-7.499-1.632z" />
          </svg>
        </div>
        <p className="font-display text-2xl font-semibold text-gray-900">{profile.username}</p>
      </div>

      <form onSubmit={handleProfileSubmit} className="space-y-6">
        <h2 className={SECTION_TITLE}>Datos de la cuenta</h2>
        <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
          <div>
            <label htmlFor="username" className={LABEL}>
              Nombre de usuario
            </label>
            <input
              id="username"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              className={INPUT}
              autoComplete="username"
            />
          </div>

          <div>
            <label htmlFor="email" className={LABEL}>
              Correo electrónico
            </label>
            <input
              id="email"
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              className={INPUT}
              autoComplete="email"
            />
          </div>
        </div>

        {profile.created_at && (
          <p className="text-sm text-gray-500">
            Miembro desde{' '}
            {formatDate(profile.created_at)}
          </p>
        )}

        {profileFormError && (
          <div role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
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
          className="rounded-lg bg-blue-600 px-5 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-700 dark:hover:bg-solid-blue-700 disabled:cursor-not-allowed disabled:bg-gray-300"
        >
          {savingProfile ? 'Guardando...' : 'Guardar cambios'}
        </button>
      </form>

      <form onSubmit={handlePasswordSubmit} className="mt-10 space-y-6">
        <h2 className={SECTION_TITLE}>Cambiar contraseña</h2>

        <div className="grid grid-cols-1 gap-6 sm:grid-cols-3">
          <PasswordField
            id="current-password"
            label="Contraseña actual"
            value={currentPassword}
            onChange={setCurrentPassword}
            autoComplete="current-password"
          />
          <PasswordField
            id="new-password"
            label="Nueva contraseña"
            value={newPassword}
            onChange={setNewPassword}
            autoComplete="new-password"
          />
          <PasswordField
            id="confirm-password"
            label="Confirmar nueva contraseña"
            value={confirmPassword}
            onChange={setConfirmPassword}
            autoComplete="new-password"
          />
        </div>

        {passwordFormError && (
          <div role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
            {passwordFormError}
          </div>
        )}

        {passwordMessage && (
          <div className="rounded-lg border border-green-200 bg-green-50 px-3 py-2 text-sm text-green-700">
            {passwordMessage}
          </div>
        )}

        <div className="flex items-center gap-3">
          <button
            type="submit"
            disabled={!hasPasswordInput || savingPassword}
            className="rounded-lg bg-blue-600 px-5 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-700 dark:hover:bg-solid-blue-700 disabled:cursor-not-allowed disabled:bg-gray-300"
          >
            {savingPassword ? 'Guardando...' : 'Guardar cambios'}
          </button>
          <button
            type="button"
            onClick={() => {
              setCurrentPassword('')
              setNewPassword('')
              setConfirmPassword('')
              setPasswordFormError(null)
              setPasswordMessage(null)
            }}
            disabled={!hasPasswordInput || savingPassword}
            className="rounded-lg border border-gray-300 bg-white px-5 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
          >
            Cancelar cambios
          </button>
        </div>
      </form>
    </div>
  )
}
