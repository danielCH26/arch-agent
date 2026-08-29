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
  model?: string | null
  base_url?: string | null
  has_api_key?: boolean | null
}

export interface AvailableModelsResponse {
  models: string[]
  base_url: string
  cached: boolean
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

export async function fetchAvailableModelsFromBackend(): Promise<AvailableModelsResponse> {
  return apiFetch<AvailableModelsResponse>('/api/llm/wizard/available-models', {
    method: 'GET',
  })
}
