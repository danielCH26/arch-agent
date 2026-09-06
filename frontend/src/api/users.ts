import { apiFetch } from './client'

export interface UserProfile {
  id: number
  username: string
  email: string
  created_at: string | null
}

export interface UpdateProfileInput {
  username: string
  email: string
}

export interface ChangePasswordInput {
  current_password: string
  new_password: string
}

export async function getUserProfile(): Promise<UserProfile> {
  return apiFetch<UserProfile>('/api/users/me')
}

export async function updateUserProfile(input: UpdateProfileInput): Promise<UserProfile> {
  return apiFetch<UserProfile>('/api/users/me', {
    method: 'PATCH',
    body: JSON.stringify(input),
  })
}

export async function changeUserPassword(input: ChangePasswordInput): Promise<void> {
  return apiFetch<void>('/api/users/me/password', {
    method: 'PUT',
    body: JSON.stringify(input),
  })
}
