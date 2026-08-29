import { useEffect, useState } from 'react'
import { getUserProfile, UserProfile } from '../api/users'

export function ProfilePage() {
  const [profile, setProfile] = useState<UserProfile | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getUserProfile()
      .then((p) => setProfile(p))
      .catch(() => setError('Error al cargar el perfil'))
      .finally(() => setLoading(false))
  }, [])

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
    <div className="max-w-md">
      <h1 className="text-2xl font-bold text-gray-900 mb-6">Mi Perfil</h1>

      <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6 space-y-4">
        <div>
          <span className="text-sm font-medium text-gray-500">Nombre de usuario</span>
          <p className="text-gray-900">{profile.username}</p>
        </div>

        <div>
          <span className="text-sm font-medium text-gray-500">Correo electrónico</span>
          <p className="text-gray-900">{profile.email}</p>
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
      </div>
    </div>
  )
}
