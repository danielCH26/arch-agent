## 1. Benchmark data + classifier

- [ ] 1.1 Crear `app/core/llm_model_benchmarks.yaml` con Tier 1 estricto (OpenAI o-series + GPT-4o/4-turbo, Anthropic Claude 3.5/3.7/4 Sonnet/Opus, Google Gemini 2.5/2.0 Pro, Meta Llama 3.1 405B / 3.3 70B, MiniMax-M3). Citar fuente de cada score en comentario YAML.
- [ ] 1.2 Crear `app/core/llm_model_benchmarks.py` con `load_benchmarks()` (cached, validates schema, raises `LLMBenchmarkFileError` on malformed YAML) y constante `MMLU_TIER1_THRESHOLD = 85.0`.
- [ ] 1.3 Crear `app/core/model_classifier.py` con `classify_model(model_id: str) -> dict` y `filter_by_tier(model_ids: list[str]) -> dict`. Pure functions, no DB.
- [ ] 1.4 Tests `tests/core/test_model_classifier.py` cubriendo los 4 tiers + partition de lista mixta.

## 2. Backend: 3 wizard endpoints

- [ ] 2.1 En `app/api/llm_config.py`: agregar Pydantic models `WizardStep1Request(base_url)`, `WizardStep2Request(base_url, api_key)`, `WizardStep3Request(base_url, api_key, model, allow_unknown_model=False)`.
- [ ] 2.2 Agregar endpoint `POST /api/llm/wizard/step1` que valida URL con `httpx.get("{base_url}/models", timeout=10)` y key dummy. Devuelve 200 si 200/401/403, 400 si 404/timeout/conn error.
- [ ] 2.3 Agregar endpoint `POST /api/llm/wizard/step2` que testea conexion con Bearer key. Devuelve 200 si 200, 400 con detail específico si 401/timeout/conn error.
- [ ] 2.4 Agregar endpoint `POST /api/llm/wizard/step3` que guarda config (igual a POST /api/llm/config actual). Si `allow_unknown_model=False` y el modelo no está en tier1 del benchmark, devolver 400 con detail "Modelo no está en tier 1. Use allow_unknown_model=true para forzar."
- [ ] 2.5 Marcar `POST /api/llm/config/validate` como deprecated: cambiar handler para devolver 410 Gone con detail "Use /api/llm/wizard/step1 or /step2 instead". Mantener endpoint vivo (no eliminar) por 1 release.
- [ ] 2.6 Tests `tests/api/test_llm_wizard.py` con httpx mockeado (no pegamos a providers reales). Cubrir: step1 URL inválida, step1 URL válida, step2 key inválida, step2 key válida, step3 tier1 OK, step3 tier2 bloqueado sin flag, step3 tier2 OK con flag, step3 unknown OK con flag, validate viejo retorna 410.

## 3. Frontend: 3 sub-componentes del wizard

- [ ] 3.1 Crear `frontend/src/components/llm-wizard/Step1BaseUrl.tsx`. Input text, boton "Continuar" (disabled hasta que URL valida formato `^https?://.+`), llama `wizardStep1`. Muestra errores del backend o validacion client-side. Botón "Cancelar" deshabilitado en step 1 (no se puede cancelar el primer paso).
- [ ] 3.2 Crear `frontend/src/components/llm-wizard/Step2ApiKey.tsx`. Input password + toggle show/hide. Boton "Continuar" llama `wizardStep2`. Muestra errores. Botón "Cancelar" vuelve al step 1 (limpia URL del paso 1).
- [ ] 3.3 Crear `frontend/src/components/llm-wizard/Step3ModelSelect.tsx`. Recibe `available_models` (lista cruda del provider), llama `filterByTier()` client-side. Renderiza dropdown agrupado: tier1 primero (badge verde "Recomendado"), unknown/tier2 después (badge amber "Sin score conocido"), bloqueados NO aparecen. Botón "Cancelar" revela free-text input. Botón "Guardar" llama `wizardStep3` con `allow_unknown_model=true` si modelo es unknown o viene de free-text.
- [ ] 3.4 Crear `frontend/src/components/llm-wizard/LLMWizard.tsx` (componente orquestador). State local: `{step: 1|2|3, baseUrl, apiKey, models, selectedModel, allowUnknown}`. Renderiza el step activo según `step`. Renderiza indicador de progreso (3 dots / barra). En step 1, pre-llena `baseUrl` con `getLLMConfig()` si existe.

## 4. Frontend: integración con SettingsPage + API client

- [ ] 4.1 Crear `frontend/src/api/wizard.ts` con `wizardStep1`, `wizardStep2`, `wizardStep3`. Mantener `getLLMConfig` y `saveLLMConfig` en `frontend/src/api/llm.ts` (saveLLMConfig queda deprecated, lo borraremos en release siguiente).
- [ ] 4.2 Modificar `frontend/src/pages/SettingsPage.tsx`: reemplazar `<LLMConfigForm />` por `<LLMWizard />`. Import path del wizard.
- [ ] 4.3 Eliminar `frontend/src/components/LLMConfigForm.tsx` (ya no se usa).

## 5. Tests E2E manuales + validación

- [ ] 5.1 Rebuild imagen backend, restart container, verificar que los 3 nuevos responden con `curl`.
- [ ] 5.2 Rebuild imagen SPA, restart container, abrir http://localhost:5173/settings/llm con `testuser / Test1234!` y completar el wizard con un provider real (Ollama local o OpenAI).
- [ ] 5.3 Verificar que en step 3, los tier1 aparecen con badge verde y los unknown con badge amber.
- [ ] 5.4 Verificar que un modelo tier-bloqueado (gpt-3.5-turbo si está en el YAML) NO aparece en el dropdown.
- [ ] 5.5 Verificar el free-text fallback: tipear un modelo custom y guardar con `allow_unknown_model=true`.
- [ ] 5.6 Verificar que el backend rechaza un tier2 sin `allow_unknown_model=true` (devuelve 400).

## 6. Docs + commit

- [ ] 6.1 Agregar entrada al `README.md` sección "Configuración de LLM" describiendo el wizard y los tiers.
- [ ] 6.2 Commit + push a `feature/chainlit-api` con mensaje `feat(llm): 3-step wizard for LLM config + MMLU tier filter`.