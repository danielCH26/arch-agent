import { apiFetch } from './client'

export interface WizardStep1Request {
  base_url: string
}

export interface WizardStep2Request {
  base_url: string
  api_key: string
}

export interface WizardStep3Request {
  base_url: string
  api_key: string
  model: string
  allow_unknown_model: boolean
}

export interface WizardStepResponse {
  success: boolean
  message: string
  model?: string
  base_url?: string
  has_api_key?: boolean
}

export async function wizardStep1(body: WizardStep1Request): Promise<WizardStepResponse> {
  return apiFetch<WizardStepResponse>('/api/llm/wizard/step1', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export async function wizardStep2(body: WizardStep2Request): Promise<WizardStepResponse> {
  return apiFetch<WizardStepResponse>('/api/llm/wizard/step2', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export async function wizardStep3(body: WizardStep3Request): Promise<WizardStepResponse> {
  return apiFetch<WizardStepResponse>('/api/llm/wizard/step3', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export async function fetchAvailableModels(baseUrl: string, apiKey: string): Promise<string[]> {
  const url = `${baseUrl.replace(/\/$/, '')}/models`
  const response = await fetch(url, {
    headers: { 'Authorization': `Bearer ${apiKey}` },
  })
  if (!response.ok) throw new Error(`Failed to fetch models: ${response.status}`)
  const data = await response.json()
  return (data.data || data.models || [])
    .map((m: unknown) => {
      if (typeof m === 'string') return m
      if (m && typeof m === 'object') {
        const obj = m as { id?: unknown; name?: unknown }
        if (typeof obj.id === 'string') return obj.id
        if (typeof obj.name === 'string') return obj.name
      }
      return null
    })
    .filter((m: string | null): m is string => Boolean(m))
}
