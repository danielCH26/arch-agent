import { apiFetch, ApiError } from './client'

export interface UserProfile {
  id: number
  username: string
  email: string
  created_at: string | null
}

export interface UserProfileUpdate {
  username?: string
  email?: string
}

export async function getUserProfile(): Promise<UserProfile> {
  return apiFetch<UserProfile>('/api/users/me')
}

export async function updateUserProfile(payload: UserProfileUpdate): Promise<UserProfile> {
  return apiFetch<UserProfile>('/api/users/me', {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}
