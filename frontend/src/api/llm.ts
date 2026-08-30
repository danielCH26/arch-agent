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

export interface BenchmarkEntry {
  model_id: string
  mmlu_score: number
  source: string
}

export interface BenchmarksResponse {
  models: BenchmarkEntry[]
  tier1_threshold: number
  tier2_threshold: number
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

export async function getBenchmarks(): Promise<BenchmarksResponse> {
  /**
   * Lista de modelos con score MMLU + thresholds de tier, expuesta por
   * GET /api/llm/benchmarks. La fuente de verdad vive en el backend
   * (app/core/llm_model_benchmarks.json) y el frontend la usa para
   * clasificar modelos en tier1/tier2/unknown/blocked en el wizard.
   *
   * Sin auth. Cachear del lado del cliente (TTL horas es OK; los scores
   * cambian solo via PR).
   */
  return apiFetch<BenchmarksResponse>('/api/llm/benchmarks')
}
