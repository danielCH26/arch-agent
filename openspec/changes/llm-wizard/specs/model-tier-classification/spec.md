## ADDED Requirements

### Requirement: Model classification is driven by a versioned YAML file
The system SHALL load a benchmark YAML file at `app/core/llm_model_benchmarks.yaml` containing MMLU scores for known LLM models. The file is the single source of truth and is editable via PR.

#### Scenario: YAML file is loaded on module import
- **WHEN** the Python process imports `app.core.llm_model_benchmarks`
- **THEN** the YAML file is loaded once and cached; subsequent calls use the cached data

#### Scenario: Missing or malformed YAML raises at startup
- **WHEN** the YAML file does not exist OR contains invalid syntax OR has missing required fields
- **THEN** the module import raises `LLMBenchmarkFileError` with a specific message indicating what is wrong

#### Scenario: Each model entry has model_id and mmlu_score
- **WHEN** the YAML is loaded successfully
- **THEN** each entry MUST have a `model_id` (string, matches the ID returned by the provider's `/models` endpoint) and an `mmlu_score` (float between 0 and 100); entries missing these fields are skipped with a warning

### Requirement: Classify model into tier based on MMLU score
The system SHALL classify a model into one of four tiers: `tier1` (MMLU >= 85), `tier2` (60 <= MMLU < 85), `blocked` (MMLU < 60), or `unknown` (not in the benchmark file).

#### Scenario: Tier 1 classification
- **WHEN** `classify_model("gpt-4o")` is called and the YAML has `gpt-4o: { mmlu_score: 88.7 }`
- **THEN** the function returns `{"tier": "tier1", "mmlu_score": 88.7}`

#### Scenario: Tier 2 classification
- **WHEN** `classify_model("gpt-4o-mini")` is called and the YAML has `gpt-4o-mini: { mmlu_score: 82.0 }`
- **THEN** the function returns `{"tier": "tier2", "mmlu_score": 82.0}`

#### Scenario: Blocked classification
- **WHEN** `classify_model("gpt-3.5-turbo")` is called and the YAML has `gpt-3.5-turbo: { mmlu_score: 57.0 }`
- **THEN** the function returns `{"tier": "blocked", "mmlu_score": 57.0}`

#### Scenario: Unknown classification
- **WHEN** `classify_model("some-brand-new-model-2026")` is called and the YAML does NOT contain that model
- **THEN** the function returns `{"tier": "unknown", "mmlu_score": None}`

### Requirement: Filter model list by tier
The system SHALL provide a function that takes a list of model IDs and returns three groups: `tier1` (selectable, badge "Recomendado"), `unknown_or_tier2` (selectable with warning), and `blocked` (excluded from UI).

#### Scenario: Mixed list is partitioned correctly
- **WHEN** `filter_by_tier(["gpt-4o", "gpt-4o-mini", "gpt-3.5-turbo", "future-model"])` is called
- **THEN** the function returns `{tier1: ["gpt-4o"], unknown_or_tier2: ["gpt-4o-mini", "future-model"], blocked: ["gpt-3.5-turbo"]}`

### Requirement: Initial benchmark YAML covers Tier 1 strict models
The initial `app/core/llm_model_benchmarks.yaml` MUST include at least the following Tier 1 strict models with their MMLU scores from public sources (papers, OpenLLM Leaderboard, vendor docs):

- OpenAI: `gpt-4o`, `gpt-4-turbo`, `o1`, `o3-mini`, `o4-mini`
- Anthropic: `claude-3-5-sonnet-latest`, `claude-3-7-sonnet`, `claude-sonnet-4`, `claude-opus-4`
- Google: `gemini-2.5-pro`, `gemini-2.0-pro`
- Meta: `llama-3.1-405b-instruct`, `llama-3.3-70b-instruct`
- MiniMax: `MiniMax-M3`

Other Tier 2 / commonly used models (GPT-4o-mini, Claude Haiku, Gemini Flash, smaller Llama) MAY be included at the discretion of the maintainer. Blocked-tier models (GPT-3.5, older models) MAY be listed so the classifier can recognize them and hide them from the UI.

#### Scenario: Initial YAML is committed with the change
- **WHEN** the change is applied
- **THEN** `app/core/llm_model_benchmarks.yaml` exists and contains at least the Tier 1 models listed above

#### Scenario: MMLU scores come from public sources
- **WHEN** a MMLU score is added to the YAML
- **THEN** the commit message OR a comment in the YAML MUST cite the source (paper URL, leaderboard snapshot, vendor announcement)

### Requirement: Adding new models to the YAML is a code change
The system SHALL treat the YAML as part of the codebase. Adding a new model or updating a score requires a PR (no runtime UI for editing). This guarantees audit trail and review.

#### Scenario: No runtime edit endpoint exists
- **WHEN** an authenticated admin user calls any endpoint to modify `llm_model_benchmarks.yaml`
- **THEN** the system returns 404 (no such endpoint exists)