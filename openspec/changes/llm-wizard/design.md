## Context

El usuario quiere un wizard obligatorio de 3 pasos para configurar el LLM, con control de calidad via filtrado de modelos por score MMLU. Hoy hay un form de un solo paso (`LLMConfigForm.tsx`) sin control de calidad.

**Stack relevante**:
- Backend FastAPI con endpoints actuales: `GET /api/llm/config`, `POST /api/llm/config`, `POST /api/llm/config/validate`.
- Lógica de validación de URL/provider ya existe en `app/core/llm_validator.py` (`validate_llm_config`, `get_available_models`).
- Lógica de carga de modelo LangChain ya existe en `app/core/llm_loader.py` (`build_langchain_model`).
- Encriptación de API key con Fernet ya funciona (`app/core/encryption.py`).
- DB schema: `users.llm_base_url`, `users.llm_model`, `users.encrypted_api_key`. No requiere migración.

## Goals / Non-Goals

**Goals:**
- Wizard obligatorio de 3 pasos (URL → API key → modelo) en `/settings/llm`.
- Filtrado de modelos por tier MMLU >= 85% (tier 1, recomendado), tier 2 / unknown (con warning), tier bloqueado (oculto).
- Mantener la persistencia actual (Fernet + tabla users).
- Mantener la lógica de validación de provider existente (httpx + GET /models).
- Permitir al usuario tipear manualmente un modelo no listado via free-text.

**Non-Goals:**
- UI de admin para editar el benchmark YAML (los modelos se agregan via PR).
- Rate limiting por usuario al llamar a `/models` (depende del provider).
- Streaming de respuesta del modelo durante el setup (no aplica, esto es config).
- Refactor del `LLMConfigForm.tsx` existente — se reemplaza, no se conserva.
- Migración de configs existentes (siguen funcionando, solo cambia la UI).

## Decisions

### Decision 1: 3 endpoints nuevos en lugar de 1 endpoint con step param
**Por qué**: cada paso tiene semántica distinta (URL ping sin auth, auth test, save). Separarlos hace que el backend pueda validar/limitar/cachear de forma diferente. Más explícito que un endpoint polimórfico `POST /wizard/next-step {step: 1|2|3, data}`.

**Alternativa considerada**: 1 endpoint `/wizard/next-step` con switch interno. Más simple en cantidad de endpoints pero harder to type-hint y prone a errores por typo en `step`.

### Decision 2: YAML versionado para scores MMLU
**Por qué**: simple, auditable, sin dependencias externas. El producto owner puede agregar/actualizar scores con un PR + review. Sin latencia, sin rate limits, sin downtime de API externa.

**Alternativa considerada**: fetch desde HuggingFace OpenLLM Leaderboard en runtime. Decidido en contra por los riesgos discutidos: latencia, rate limits, downtime, costo.

### Decision 3: Modelos sin score = warning, no bloqueo
**Por qué**: el provider puede haber sacado un modelo nuevo que aún no está en el benchmark file. Bloquearlo frustra al usuario. Permitirlo con warning + flag `allow_unknown_model` da flexibilidad sin perder control total.

**Alternativa considerada**: bloquear por default (fail-closed). Decidido en contra porque rompe la UX para modelos nuevos (ej: MiniMax-M3 recién salido, o GPT-5 antes de que se actualice el YAML).

### Decision 4: Modelos tier-bloqueado = ocultos del dropdown (no warning)
**Por qué**: si el provider lista `gpt-3.5-turbo` o similar, mostrarlo como "warning" le da al usuario la opción de elegirlo, contradiciendo el objetivo de calidad. Mejor ocultarlo completamente y forzar al usuario a usar free-text si lo necesita (caso atípico).

**Alternativa considerada**: mostrar todos con badge de tier. Decidido en contra porque permite bypass accidental del filtro de calidad.

### Decision 5: State del wizard en componente-local (no Zustand store global)
**Por qué**: el wizard se monta y desmonta en una sola ruta (`/settings/llm`). No necesita persistencia entre páginas. Un `useState` por paso es suficiente y testeable.

**Alternativa considerada**: Zustand store global `llmWizardStore`. Decidido en contra por over-engineering: no se comparte entre rutas, no se persiste, no se testea con mock store.

### Decision 6: Free-text fallback con flag `allow_unknown_model: true`
**Por qué**: el usuario puede querer usar un modelo custom fine-tuneado, un alias, o un modelo que el provider devuelve con un nombre distinto al del benchmark. El free-text + flag es la salida de escape.

**Alternativa considerada**: solo permitir modelos del dropdown. Decidido en contra porque rompe casos de uso legítimos (fine-tunes, modelos internos).

### Decision 7: Old `/api/llm/config/validate` retorna 410 Gone, no se elimina
**Por qué**: 410 le dice a clientes viejos explícitamente "este endpoint ya no existe, migrá". El código queda como deprecation marker por si alguien lo busca.

**Alternativa considerada**: eliminar el endpoint. Decidido en contra porque deja el routing abierto a re-introducir bugs accidentalmente.

## Risks / Trade-offs

- **[Risk] YAML desactualizado**: proveedor saca modelo nuevo, el benchmark no lo incluye, aparece como "unknown". → Mitigation: el warning UI lo marca; el product owner mantiene el YAML con cadencia.
- **[Risk] Cambiar el form rompe usuarios con config existente**: la primera vez que abran `/settings/llm` ven el wizard en paso 1 con su URL pre-llenada. → Mitigation: `Cancelar` no borra la config persistida; la próxima vez muestra la URL guardada.
- **[Risk] Step 3 con muchos modelos**: si el provider devuelve 200 modelos, el dropdown puede ser lento. → Mitigation: agrupar por tier (tier1 primero, unknown después); considerar virtual scrolling si crece.
- **[Risk] Cancelar del paso 3 malinterpretado**: el usuario puede querer "salir" no "cancelar". → Mitigation: dos botones separados ("Cancelar" = volver al modo dropdown, "Volver a proyectos" = salir del wizard).
- **[Risk] Threshold MMLU 85% muy estricto**: podría dejar afuera modelos válidos (ej: Claude 3.5 Sonnet tiene MMLU ~88 según fuente). → Mitigation: el threshold es editable en YAML; se puede tunear post-deploy con datos reales.

## Migration Plan

1. Deploy del backend con los 3 nuevos endpoints + el viejo retornando 410.
2. Deploy de la SPA con el wizard.
3. **No requiere migración de DB** — schema no cambia.
4. **No requiere reset de configs existentes** — siguen en la tabla `users`.
5. Rollback: revertir commit del backend y de la SPA. Las configs de usuarios siguen intactas.

## Open Questions

- ¿El threshold MMLU 85% queda hardcoded en el código o se hace configurable via env var? (Decisión: hardcoded por ahora, editable via PR si se necesita tunear.)
- ¿Los modelos tier-bloqueado se loggean cuando se filtran? (Para auditoría de quién intenta usar gpt-3.5). (Decisión: sí, loggear el modelo y el user_id en backend.)
- ¿El free-text valida formato (ej: `provider/model-name`) o acepta cualquier string? (Decisión: acepta cualquier string; la validación real la hace el provider al chatear.)