import { apiFetch } from './client'

export interface LLMConfigResponse {
  base_url: string | null
  model: string | null
  has_api_key: boolean
}

export interface LLMConfigSave {
  base_url: string
  model: string
  api_key: string
}

export interface ValidateRequest {
  base_url: string
  api_key: string
  model: string
}

export interface ValidateResponse {
  valid: boolean
  message: string
}

export async function getLLMConfig(): Promise<LLMConfigResponse> {
  return apiFetch<LLMConfigResponse>('/api/llm/config')
}

export async function saveLLMConfig(config: LLMConfigSave): Promise<{ message: string }> {
  return apiFetch<{ message: string }>('/api/llm/config', {
    method: 'POST',
    body: JSON.stringify(config),
  })
}

export async function validateLLMConfig(config: ValidateRequest): Promise<ValidateResponse> {
  return apiFetch<ValidateResponse>('/api/llm/config/validate', {
    method: 'POST',
    body: JSON.stringify(config),
  })
}
