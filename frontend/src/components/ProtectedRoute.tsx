import { ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { authStore } from '../stores/authStore'

interface ProtectedRouteProps {
  children: ReactNode
}

export function ProtectedRoute({ children }: ProtectedRouteProps) {
  const location = useLocation()
  const token = authStore.getState().token

  if (!token) {
    // Redirect to login with return URL
    return <Navigate to="/login" state={{ from: location.pathname }} replace />
  }

  return <>{children}</>
}
