## Why

El form actual de LLM config (`frontend/src/components/LLMConfigForm.tsx`) es un único paso con tres campos (Base URL, Modelo, API Key) que el usuario puede editar parcialmente en cualquier orden. Esto genera friccion: URLs mal tipeadas que solo se descubren al validar, modelos que no existen en el proveedor y se descubren al chatear, y cero control sobre la **calidad** del modelo elegido.

El cliente necesita garantizar que el agente siempre corra sobre **modelos de frontera** (MMLU >= 85%) porque la calidad del output impacta directamente en el producto que entrega al usuario final. Hoy cualquier modelo del proveedor (incluso tier-bajo como `gpt-4o-mini` o `llama-3.1-8b`) es seleccionable sin aviso.

## What Changes

- **Wizard de 3 pasos obligatorio** en `/settings/llm`. Reemplaza el form actual. Se renderiza SIEMPRE (no es un onboarding — el usuario siempre pasa por los 3 pasos para crear o editar la config).
  - **Paso 1**: Base URL. Valida formato y que el endpoint existe (pega a `{base_url}/models` con key dummy, espera 200/401, rechaza 404).
  - **Paso 2**: API Key. Testea conexion real con la key (pega a `{base_url}/models` con Bearer, espera 200, rechaza 401/timeout).
  - **Paso 3**: Selector de modelos. Llama a `{base_url}/models` con la key, devuelve lista filtrada contra `app/core/llm_model_benchmarks.yaml`. Dropdown organizado por tier:
    - **Tier 1 (MMLU >= 85%)**: badge "Recomendado", seleccionable por default.
    - **Tier 2 / sin score**: badge "Sin score conocido", seleccionable con confirmacion explicita.
    - **Tier bloqueado (MMLU < 60%)**: NO aparece en el dropdown.
    - **Fallback**: textbox libre si el modelo no esta en la lista del dropdown (caso "cancelar" del wizard).
- **Whitelist de modelos en YAML** (`app/core/llm_model_benchmarks.yaml`). Source of truth versionada en el repo, editable por PR. Scores MMLU de cada modelo conocido. Modelos sin entrada -> "sin score conocido" (warning, no bloqueo).
- **Endpoints nuevos** en backend (reemplazan `/api/llm/config/validate`):
  - `POST /api/llm/wizard/step1` -> valida URL (body: `{base_url}`).
  - `POST /api/llm/wizard/step2` -> valida key + test conexion (body: `{base_url, api_key}`).
  - `POST /api/llm/wizard/step3` -> guarda config (body: `{base_url, api_key, model, allow_unknown_model}`).
- **Endpoint existente `POST /api/llm/config`** se mantiene como **deprecated** (redirige a step3). Se elimina en cambio futuro.

## Capabilities

### New Capabilities
- `llm-config-wizard`: wizard obligatorio de 3 pasos para configurar el LLM del usuario, con validacion incremental y filtrado de modelos por score MMLU.
- `model-tier-classification`: clasificacion automatica de modelos LLM en tiers segun score MMLU >= 85% (tier 1), 60-85% (tier 2), < 60% (bloqueado), o desconocido (warning). Source of truth en YAML versionado.

### Modified Capabilities
- (none — el form actual no tiene spec base)

## Impact

- **Backend** (`app/api/llm_config.py`):
  - Reemplazar 3 endpoints existentes por 4 nuevos (3 wizard steps + eliminar validate).
  - Eliminar `validate_llm_config` uso desde el endpoint validate (la logica sigue en `app/core/llm_validator.py`, lo que se borra es el wrapper HTTP).
- **Backend** (`app/core/`):
  - Nuevo: `app/core/llm_model_benchmarks.py` (cargador del YAML) y `app/core/llm_model_benchmarks.yaml` (datos).
  - Nuevo: `app/core/model_classifier.py` (clasifica modelo en tier segun score).
- **Frontend** (`frontend/src/components/`):
  - Eliminar: `LLMConfigForm.tsx`.
  - Nuevo: `LLMWizard.tsx` con sub-componentes `Step1BaseUrl.tsx`, `Step2ApiKey.tsx`, `Step3ModelSelect.tsx`.
  - Modificar: `SettingsPage.tsx` para renderizar el wizard en vez del form.
  - Nuevo: estado del wizard (URL, key, modelos disponibles, modelo seleccionado) — Zustand store o componente-local state.
- **Frontend** (`frontend/src/api/`):
  - Eliminar: `validateLLMConfig` de `llm.ts`.
  - Nuevo: `wizardStep1`, `wizardStep2`, `wizardStep3` en `wizard.ts` (o extension de `llm.ts`).
- **Tests** (`tests/`):
  - Nuevo: `tests/api/test_llm_wizard.py` (3 endpoints del wizard).
  - Nuevo: `tests/core/test_model_classifier.py` (clasificacion por tier).
- **Sin impacto**: DB schema (sigue `users.llm_base_url`, `llm_model`, `encrypted_api_key`), Langfuse, Engram, Postgres, Docker config.
- **Breaking para usuarios con config previa**: ninguno. La config previa sigue funcionando. La UI cambia (siempre wizard), pero el POST a step3 acepta el mismo shape que el POST a /config original.