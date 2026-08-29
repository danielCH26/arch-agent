import { apiFetch } from './client'

export interface UserProfile {
  id: number
  username: string
  email: string
  created_at: string | null
}

export async function getUserProfile(): Promise<UserProfile> {
  return apiFetch<UserProfile>('/api/users/me')
}
