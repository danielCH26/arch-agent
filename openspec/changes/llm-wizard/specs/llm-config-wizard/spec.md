## ADDED Requirements

### Requirement: Wizard is always rendered for LLM configuration
The system SHALL always render the 3-step wizard at `/settings/llm`. There SHALL NOT be a shortcut to a single-form view, regardless of whether the user already has a saved LLM configuration.

#### Scenario: First-time user opens settings
- **WHEN** an authenticated user navigates to `/settings/llm` with no saved LLM config
- **THEN** the system renders the wizard at step 1 (Base URL) with empty fields

#### Scenario: Returning user opens settings
- **WHEN** an authenticated user navigates to `/settings/llm` with a saved LLM config (existing `base_url`, `model`, encrypted `api_key`)
- **THEN** the system renders the wizard at step 1 (Base URL) with the `base_url` field pre-filled from the saved config; `api_key` field is left empty (never pre-filled from encrypted storage)

#### Scenario: Wizard is the only path to save
- **WHEN** an authenticated user wants to change their LLM configuration
- **THEN** the user MUST complete all 3 steps; there SHALL be no way to save partial state

### Requirement: Step 1 validates the Base URL
The system SHALL validate the Base URL entered by the user before allowing navigation to step 2. Validation consists of a request to `{base_url}/models` with a dummy API key; the request MUST return a non-404 response (200, 401, 403, or 5xx that proves the endpoint exists).

#### Scenario: Valid URL passes step 1
- **WHEN** the user enters `https://api.openai.com/v1` and clicks "Continuar"
- **THEN** the system calls `POST /api/llm/wizard/step1` with `{base_url: "https://api.openai.com/v1"}`; the endpoint returns 200; the wizard advances to step 2

#### Scenario: URL with 404 fails step 1
- **WHEN** the user enters `https://example.com/no-such-endpoint` and clicks "Continuar"
- **THEN** the system calls `POST /api/llm/wizard/step1`; the endpoint returns 400 with detail "La URL no responde /models"; the wizard remains at step 1 and displays the error

#### Scenario: Invalid URL format fails client-side
- **WHEN** the user enters `not-a-url` and clicks "Continuar"
- **THEN** the system rejects the input client-side without calling the API; the wizard displays "La URL debe comenzar con http:// o https://"

#### Scenario: Step 1 timeout
- **WHEN** the Base URL responds in more than 10 seconds
- **THEN** the system displays "El proveedor no respondió en 10s. Verifica tu conexión." and remains at step 1

### Requirement: Step 2 validates the API key with a real connection test
The system SHALL test the API key entered by the user by issuing an authenticated request to `{base_url}/models` with the key. The request MUST return 200 to pass. A 401 response MUST fail step 2 with a specific "API Key inválida" message.

#### Scenario: Valid key passes step 2
- **WHEN** the user enters a valid API key and clicks "Continuar"
- **THEN** the system calls `POST /api/llm/wizard/step2` with `{base_url, api_key}`; the endpoint returns 200; the wizard advances to step 3

#### Scenario: Invalid key (401) fails step 2
- **WHEN** the user enters an invalid API key and clicks "Continuar"
- **THEN** the system calls `POST /api/llm/wizard/step2`; the endpoint returns 400 with detail "API Key inválida."; the wizard remains at step 2 and displays the error

#### Scenario: Step 2 connection error
- **WHEN** the connection to `{base_url}/models` fails (timeout, network error, 5xx)
- **THEN** the system displays a specific error message ("timeout", "no se pudo conectar", "error del proveedor") and remains at step 2

### Requirement: Step 3 displays a tier-classified model dropdown
The system SHALL query the provider's `/models` endpoint with the validated API key, filter the response through the MMLU-based classifier (see `model-tier-classification` spec), and display the models in a dropdown organized by tier.

#### Scenario: Tier 1 models are shown with "Recomendado" badge
- **WHEN** the wizard reaches step 3 with at least one model having MMLU score >= 85% in the benchmark file
- **THEN** those models appear at the top of the dropdown with a green "Recomendado" badge; the first tier-1 model is pre-selected

#### Scenario: Unknown-score models are shown with warning badge
- **WHEN** a model returned by the provider is NOT in the benchmark file (no MMLU score recorded)
- **THEN** that model appears in a separate section of the dropdown with an amber "Sin score conocido" badge; selecting it requires explicit confirmation

#### Scenario: Blocked-tier models are hidden
- **WHEN** a model returned by the provider has MMLU score < 60% in the benchmark file
- **THEN** that model SHALL NOT appear in the dropdown at all (it is not a valid selection)

#### Scenario: Free-text fallback for models not in the dropdown
- **WHEN** the user clicks "Cancelar" in step 3 OR the model the user wants is not in the dropdown
- **THEN** a free-text input becomes available; the user can type the exact model ID; clicking "Guardar" submits it with `allow_unknown_model: true` flag

#### Scenario: User selects a recommended tier-1 model
- **WHEN** the user picks `gpt-4o` from the tier-1 list (MMLU 88.7, score >= 85%) and clicks "Guardar"
- **THEN** the system calls `POST /api/llm/wizard/step3` with `{base_url, api_key, model: "gpt-4o", allow_unknown_model: false}`; the endpoint returns 200 with `{message: "Configuración guardada"}`; the user's `users.llm_model` is updated to `gpt-4o`

#### Scenario: User selects an unknown-score model via confirmation
- **WHEN** the user picks a model with badge "Sin score conocido" and confirms the warning dialog
- **THEN** the system submits with `allow_unknown_model: true`; the backend stores it regardless of benchmark absence

#### Scenario: User submits model via free-text
- **WHEN** the user types a model name in the free-text field and clicks "Guardar"
- **THEN** the system submits with `allow_unknown_model: true`; the backend stores it regardless of benchmark absence

### Requirement: Cancel button in step 3 enables manual model entry
The system SHALL always show a "Cancelar" button in step 3 that switches the dropdown to a free-text input. The user SHALL be able to type any model ID even if it does not appear in the dropdown, and the form SHALL submit with `allow_unknown_model: true`.

#### Scenario: Cancel button reveals free-text input
- **WHEN** the user clicks "Cancelar" in step 3
- **THEN** the dropdown is replaced by a text input pre-filled with the currently selected model (or empty); the "Guardar" button remains enabled

#### Scenario: User saves a manual model
- **WHEN** the user types `claude-3-7-sonnet-custom-fine-tune` in the free-text input and clicks "Guardar"
- **THEN** the system submits with `model: "claude-3-7-sonnet-custom-fine-tune", allow_unknown_model: true`; the backend stores it; the wizard exits to the projects page

### Requirement: Wizard endpoints replace the old validate endpoint
The system SHALL expose three new endpoints and deprecate the old `/api/llm/config/validate`. The new endpoints are documented in `design.md`.

#### Scenario: Old validate endpoint is deprecated
- **WHEN** the SPA calls `POST /api/llm/config/validate`
- **THEN** the backend returns 410 Gone with detail "Use /api/llm/wizard/step1 or /step2 instead"

#### Scenario: New wizard endpoints respond
- **WHEN** the SPA calls any of `POST /api/llm/wizard/step1`, `/step2`, or `/step3`
- **THEN** the backend validates the request, runs the step-specific logic, and returns the appropriate success or error response

### Requirement: Cancel button keeps the user in the wizard
The system SHALL provide a "Cancelar" button at every step of the wizard. Clicking "Cancelar" SHALL clear the current step's field and return the user to step 1 with empty fields. The previously saved config (if any) SHALL NOT be modified until the user completes all 3 steps.

#### Scenario: User cancels from step 2 with existing config
- **WHEN** the user is at step 2 with a previously saved config and clicks "Cancelar"
- **THEN** the wizard returns to step 1 with empty fields; the saved config in the database remains unchanged; the next time the user opens `/settings/llm`, the step-1 field shows the previously saved URL (not the empty state from the cancel)