# Tasks: Chainlit API Replacement

## Review Workload Forecast

Changed lines: ~1,400 (prod ~950, tests ~450). Risk: **High**. Chained PRs: **Yes**.
Split: PR1 Foundation+Auth → PR2 Projects+LLM+Docs → PR3 Chat+Tests.
Delivery: auto-chain (feature-branch-chain).
Chain strategy: feature-branch-chain.

**PR 1: COMPLETED** ✅ (tasks 1.1-1.5, 2.1-2.2 — Foundation + Auth)
**PR 2: COMPLETED** ✅ (tasks 3.1-4.3 — Projects + LLM Config + Documents)
**PR 3: COMPLETED** ✅ (tasks 5.1-7.7 — Chat Streaming + Chainlit Cleanup) [Tests pending - Phase 7 not executed]

### Work Units

| # | Goal | PR | Rollback |
|---|------|----|----------|
| 1 | JWT core + `get_current_user` | PR1 | drop `app/api/` |
| 2 | auth register/login/logout | PR1 | drop `app/api/auth.py` |
| 3 | Projects CRUD + phase | PR2 | drop `app/api/projects.py` |
| 4 | LLM config endpoints | PR2 | drop `app/api/llm_config.py` |
| 5 | Document upload/list/delete | PR2 | drop `app/api/documents.py` |
| 6 | SSE chat + cleanup | PR3 | drop `app/api/chat.py` |
| 7 | Test suite wiring | PR3 | revert test files |

## Phase 1: Foundation

- [x] 1.1 Create empty `app/api/__init__.py`.
- [x] 1.2 Add `JWT_SECRET_KEY`, `JWT_ALGORITHM=HS256`, `JWT_EXPIRES_MINUTES=60` to `.env.example`.
- [x] 1.3 `app/core/jwt.py`: `create_access_token`, `verify_token`, `JWTError`; reads `JWT_SECRET_KEY`.
- [x] 1.4 `app/api/dependencies.py`: `JWT_REVOKED: set[str]` + `get_current_user` returning `user_id` or 401.
- [x] 1.5 `app/api/sse.py`: `StreamingSSECallbackHandler` queuing tokens on `on_llm_new_token`.

## Phase 2: Auth

- [x] 2.1 `app/api/auth.py`: `POST /api/auth/register|login|logout`; logout adds `jti`→`JWT_REVOKED`.
- [x] 2.2 Wire `app.api.auth.router` in `server.py`; keep Jinja `/register`; remove `mount_chainlit`.

## Phase 3: Projects

- [x] 3.1 `app/api/projects.py`: `GET/POST /api/projects`, `GET/DELETE /api/projects/{id}`, `GET /api/projects/{id}/phase`, `POST /api/projects/{id}/advance|mark-ready`.
- [x] 3.2 Reuse `app.py` `create_project`/`delete_project`/`get_project`/`advance_phase`/`mark_phase_ready`; map `ValidationError`→400/404; 403/404 on foreign.
- [x] 3.3 Include router in `server.py`. curl `/api/projects`.

## Phase 4: LLM Config + Documents

- [x] 4.1 `app/api/llm_config.py`: `GET/POST /api/llm/config`, `POST /api/llm/config/validate`; never leak `api_key`; reuse `validate_llm_config`, `save_user_llm_config`, `clear_session_cache`.
- [x] 4.2 `app/api/documents.py`: `POST /api/documents/upload` (multipart, ≤10MB, .pdf/.md), `GET /api/documents/{project_id}`, `DELETE /api/documents/{id}`; spool → `process_file` → `save_document`/`overwrite_document`/`check_duplicate`.
- [x] 4.3 Wire both routers in `server.py`. Both prefixes respond.

## Phase 5: Chat Streaming

- [x] 5.1 `app/api/chat.py` `POST /api/chat` → `StreamingResponse(media_type="text/event-stream")`; model via `build_langchain_model(user_id)`; 409 on `LLMConfigError`, 404 on foreign, 400 if `project_id is None`.
- [x] 5.2 Emit `event: token` per `on_llm_new_token`, terminate `event: done`; on error emit `event: error` then close.
- [x] 5.3 Wire router in `server.py`. `curl -N /api/chat` returns SSE.

## Phase 6: Cleanup

- [x] 6.1 `app.py`: drop `@cl.on_message`, `@cl.on_chat_start`, `@cl.on_chat_end`, all `@cl.action_callback`; keep `PHASES`, `get_user_by_login`, `create_project`, `advance_phase`, `mark_phase_ready`.
- [x] 6.2 Remove `chainlit` from `requirements.txt` (keep `pyjwt`, `python-multipart`, `fastapi`, `uvicorn`, `httpx`). `pip check` post-uninstall.
- [x] 6.3 `server.py`: mount Jinja `/register`, every `app.api.*` router, no `mount_chainlit`. `/docs` lists all routes.

## Phase 7: Tests

- [ ] 7.1 `tests/api/__init__.py` + `conftest.py` with `client` (TestClient), `auth_token`, `db_session` fixtures.
- [ ] 7.2 `tests/api/test_auth.py`: register-200, register-409, login-username, login-email, login-401, logout-204, logout-rejects-reused.
- [ ] 7.3 `tests/api/test_projects.py`: list-empty, create, get-foreign-403, delete-foreign-404, advance-when-not-ready-400, advance-happy, mark-ready-idempotent.
- [ ] 7.4 `tests/api/test_llm_config.py`: GET-no-config, GET-with-config (no `api_key`), POST-encrypts-key, validate-401-bad-key, validate-400-bad-url.
- [ ] 7.5 `tests/api/test_documents.py`: upload-pdf-201, upload-md-201, upload-12mb-400, upload-docx-400, list-empty, list-foreign-404, delete-foreign-404, duplicate-create_new_version-201.
- [ ] 7.6 `tests/api/test_chat.py`: 401-no-jwt, 400-no-project, 404-foreign, 409-no-llm-config, 200-sse-shape (mocked agent).
- [ ] 7.7 Gate: `pytest -q` exits 0; `grep -q chainlit requirements.txt` exits 1.