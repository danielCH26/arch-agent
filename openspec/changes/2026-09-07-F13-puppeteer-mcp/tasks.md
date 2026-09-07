# Tasks: F13 — Puppeteer MCP (Render Mermaid → PNG)

| Field | Value |
|---|---|
| Change slug | `F13-puppeteer-mcp` |
| Capabilities (NEW) | `puppeteer-mcp-integration`, `chat-attachments` |
| Capability (DELTA) | `engram-conversation-memory` (REQ-EM-DELTA-1 `attachments JSONB` column) |
| Branch | `feature/F13-puppeteer-mcp` @ `4c5a9d3` (DO NOT switch) |
| Base | `feature/F11-context7-mcp` @ `4c5a9d3` (F11 + F12 merged) |
| Issue | [#17 — [F13] Puppeteer MCP integrado](https://github.com/danielCH26/arch-agent/issues/17) |
| Spec | `openspec/specs/puppeteer-mcp-integration/spec.md` (5 REQ, 7 SCN) + `openspec/specs/chat-attachments/spec.md` (3 REQ, 6 SCN) + `openspec/specs/engram-conversation-memory/spec.md` DELTA-1 |
| Design | `openspec/changes/2026-09-07-F13-puppeteer-mcp/design.md` (locked) |
| Proposal | `openspec/changes/2026-09-07-F13-puppeteer-mcp/proposal.md` (locked) |
| ADR | `docs/adr/013-puppeteer-mcp.md` (to add in T13.4.6) |
| Engram topic_key | `sdd/F13-puppeteer-mcp/tasks` |
| Phase | `sdd-tasks` |
| Artifact store | hybrid (OpenSpec file + Engram upsert) |
| Delivery strategy | `single-pr` (cached preflight) |
| Size exception | **APPROVED by user this session** for ~1,155 LoC single PR; implementation rolls out as 17 work-unit commits inside that one PR (work-unit-commits skill still applies for commit-level reviewability) |

Relationship to prior phases: this file converts `design.md` §5 (file-by-file inventory), §6 (REQ → test file), §7 (migration plan) and §8 (LOC cap Q-NEW-LOC-CAP) into ordered, dependency-aware tasks. The user-approved `size:exception` resolves §8 Q-NEW-LOC-CAP toward option (A) single PR; this artifact preserves the chained-PR work units as **commits inside the single PR** so `git bisect` and incremental review stay clean.

LoC convention: **LoC = authored source lines (added + modified) in `app/`, `frontend/`, `migrations/`, `schema.sql`, `docker-compose.yml`, `.env.example`, `requirements.txt`, `infrastructure/`.** Test LoC tracked separately. `docs/adr/` NOT counted against the budget.

---

## 1. Forecast summary

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: size-exception
400-line budget risk: High (mitigated by size:exception)

| Phase | Slice | Tasks | Prod LoC | Test LoC | REQ / SCN covered | Target test files |
|---|---|---|---|---|---|---|
| **Phase 1** Backend infra + transport | 1.1 deps; 1.2 sidecar Dockerfile; 1.3 compose wiring; 1.4 env vars | 4 | ~280 | 0 | REQ-PMCP-2 / SCN-3 (env), ADR-013 | (build only) |
| **Phase 2** Backend logic | 2.1–2.10 puppeteer_mcp.py, agent, db, message_store, models, attachment_tokens, chat persist, attachments route | 10 | ~540 | 0 | REQ-PMCP-1..4, REQ-ATT-1..3, REQ-EM-DELTA-1 | (unit + integration tests land in Phase 4) |
| **Phase 3** Frontend | 3.1 api/chat; 3.2 stores/chatStore; 3.3 MessageBubble; 3.4 ChatWindow; 3.5 MessageBubble.test.tsx | 5 | ~180 | 0 | REQ-PMCP-1 (frontend), REQ-ATT-3 (frontend) | (vitest extensions in Phase 4) |
| **Phase 4** Tests + ADR + docs | 4.1 puppeteer_mcp; 4.2 attachment_tokens; 4.3 attachments endpoint; 4.4 chat SSE; 4.5 chatStore; 4.6 ADR-013 | 6 | ~155 | ~350 | ALL SCN-1..13 (red-tests live with green tasks they cover) | `tests/core/test_puppeteer_mcp.py`, `tests/core/test_attachment_tokens.py`, `tests/api/test_attachments.py`, `tests/api/test_chat.py`, `frontend/src/stores/__tests__/chatStore.test.ts`, `docs/adr/013-puppeteer-mcp.md` |
| **GRAND TOTAL** | | **25 tasks / 17 commits** | **~1,155** | **~350** | **8/8 NEW REQ, 13/13 SCN, 1/1 DELTA** | **≈1,505 changed lines** |

Budget verdict: grand total ~1,505 changed lines. Above the 400-line single-PR cap (1,155 prod LoC alone) — **mitigated by user-approved `size:exception` for single-PR delivery this session** (cached preflight, do not re-ask). Largest single commit in the work-unit map ≤ 200 LoC (most ≤ 150); reviewer can scan each commit independently even though they land in one PR. No commit is non-buildable.

---

## 2. Delivery decision (single-PR with size:exception)

- **Chained PRs required: NO** — user pre-approved `size:exception` for single-PR (~1,155 LoC) delivery this session. Cached at preflight; do not re-ask.
- **chain_strategy: `size-exception`** — recorded in the Review Workload Forecast below; the orchestrator's Review Workload Guard sees `Decision needed before apply: No` and proceeds.
- **Work-unit discipline (commit-by-commit) STILL APPLIES.** Each of the 25 tasks lands as one of 17 conventional commits inside the single PR. Each commit compiles + passes its focused tests independently; `git bisect` stays clean.
- **Mandatory sub-splits applied per `work-unit-commits` skill:**
  - `puppeteer_mcp.py` (200 LoC) → 3 commits (scaffold / allow-list / rate-limit). Each ≤ 100 LoC.
  - `chat.py` (60 LoC delta) → 1 commit after `message_store.py` and `attachment_tokens.py` land (so the persist path compiles end-to-end).
  - Tests ship WITH the behaviour they verify per work-unit-commits rule "Keep tests with code". Phase-4 test tasks correspond 1:1 to Phase-2 green tasks.

---

## 3. Phase 1 — Backend infra + transport (~280 LoC)

**Deployable checkpoint**: `docker compose build puppeteer-mcp` succeeds; `wget --spider http://puppeteer-mcp:8931/health` returns 200 inside the docker network. Backend image unchanged. No Python imports touched yet. No production behaviour change.

### T13.1.1 — chore(deps): pin itsdangerous==2.1.2

- **Files**: `requirements.txt` (+1)
- **Action**: append `itsdangerous==2.1.2` (signed-token auth for `/api/chat/attachments/{id}`).
- **Test**: `docker compose exec backend pip show itsdangerous` → version `2.1.2`.
- **Commit**: `chore(deps): add itsdangerous==2.1.2`
- **Risk**: low. Rollback: remove the line; nothing else imports it yet.

### T13.1.2 — chore(infra): create puppeteer-mcp sidecar image

- **Files**:
  - `infrastructure/puppeteer-mcp/Dockerfile` (NEW, ~30)
  - `infrastructure/puppeteer-mcp/entrypoint.sh` (NEW, ~10)
  - `infrastructure/puppeteer-mcp/.dockerignore` (NEW, ~5)
- **Action**: `FROM node:20-bookworm-slim`; install system libs (`libnss3 libatk1.0-0 libatk-bridge2.0-0 libxss1 libasound2 libgbm1 libcups2 fonts-liberation ca-certificates`); `RUN npm i -g @modelcontextprotocol/server-puppeteer` (pre-bake); warm-up + `npx ... --port 8931` in entrypoint.
- **Test**: `docker compose build puppeteer-mcp` → exit 0; image ~600 MB.
- **Commit**: `chore(infra): add puppeteer-mcp sidecar Dockerfile + entrypoint`
- **Risk**: low. Rollback: delete the directory; compose service in T13.1.3 already references it.

### T13.1.3 — chore(compose): wire puppeteer-mcp service + healthcheck + backend depends_on

- **Files**: `docker-compose.yml` (+25)
- **Action**: new `puppeteer-mcp:` service (build context `./infrastructure/puppeteer-mcp`, `mem_limit: 512m`, `restart: unless-stopped`, healthcheck via `wget --spider http://localhost:8931/health || exit 0`); `backend.depends_on` gains `puppeteer-mcp: condition: service_started`; `backend.environment` gains `PUPPETEER_MCP_URL: http://puppeteer-mcp:8931/mcp`.
- **Test**: `docker compose up -d puppeteer-mcp backend` → both healthy; `wget --spider http://puppeteer-mcp:8931/health` returns 200 from inside `backend` shell.
- **Commit**: `chore(compose): wire puppeteer-mcp service + healthcheck`
- **Risk**: low. Rollback: revert the diff; no Python code touched yet.

### T13.1.4 — chore(env): add PUPPETEER_* vars to .env.example

- **Files**: `.env.example` (+4)
- **Action**: append `PUPPETEER_MCP_URL=http://puppeteer-mcp:8931/mcp`, `PUPPETEER_RENDER_TIMEOUT_SECONDS=15`, `PUPPETEER_MAX_RENDER_BYTES=2097152`, `PUPPETEER_RENDER_RATE_LIMIT_PER_MINUTE=5` (mirror F11/F12 block near line 98).
- **Test**: `grep -E '^PUPPETEER_' .env.example` returns 4 lines.
- **Commit**: `chore(env): add PUPPETEER_* vars to .env.example`
- **Risk**: low. Rollback: delete the lines.

**Phase 1 end-of-phase verification**: `docker compose build puppeteer-mcp && docker compose up -d puppeteer-mcp && docker compose exec puppeteer-mcp wget --spider http://localhost:8931/health` → exit 0. Backend untouched.

---

## 4. Phase 2 — Backend logic (~540 LoC)

**Deployable checkpoint**: backend container can construct `MultiServerMCPClient` to the sidecar and fetch `puppeteer_screenshot`; `_persist_turn` writes attachment rows in the same transaction; `GET /api/chat/attachments/{id}` returns 200 + correct headers. Frontend still ignores `event: attachment` (Phase 3 work). Phase-4 tests verify the whole path.

### T13.2.1 — feat(puppeteer_mcp): scaffold client + PuppeteerUnavailable + reset_client_for_tests

- **Files**: `app/core/puppeteer_mcp.py` (NEW, ~70)
- **Action**: module-level `_CLIENT` singleton; `build_puppeteer_client()` (reads `PUPPETEER_MCP_URL` at call time, constructs `MultiServerMCPClient({"puppeteer": {"transport": "streamable_http", "url": ..., "timeout": 30.0}})`); `class PuppeteerUnavailable(Exception)` with sub-reasons `puppeteer_timeout` / `puppeteer_unavailable` / `puppeteer_rate_limited` / `puppeteer_byte_cap`; `reset_client_for_tests()`. NO allow-list filter yet (T13.2.2), NO rate-limit yet (T13.2.3).
- **Test** (lands in T13.4.1): `tests/core/test_puppeteer_mcp.py::test_build_puppeteer_client_*` and `test_puppeteer_unavailable_reasons`.
- **Commit**: `feat(puppeteer_mcp): scaffold client + PuppeteerUnavailable + reset_client_for_tests`
- **Risk**: low. Rollback: `rm app/core/puppeteer_mcp.py`.

### T13.2.2 — feat(puppeteer_mcp): add positive tool allow-list filter (REQ-PMCP-2)

- **Files**: `app/core/puppeteer_mcp.py` (+30)
- **Action**: `_PUPPETEER_ALLOWED_TOOLS = frozenset({"puppeteer_screenshot"})`; `get_puppeteer_tools(client=None)` (mirrors `context7_mcp.py:172-215`) — wraps `client.get_tools(server_name="puppeteer")` in `asyncio.wait_for(timeout=15.0)`, returns `[t for t in raw if t.name in _PUPPETEER_ALLOWED_TOOLS]`. `puppeteer_navigate` / `_click` / `_fill` / `_select` / `_hover` are filtered OUT before reaching the LLM (REQ-PMCP-2 SCN-PMCP-3).
- **RED test** (lands in T13.4.1): recorded fixture of full upstream tool set (8 names) → `get_puppeteer_tools()` returns exactly `["puppeteer_screenshot"]`.
- **Commit**: `feat(puppeteer_mcp): add positive tool allow-list filter`
- **Risk**: high (security invariant). Rollback: revert the filter line; keep the helper, the LLM temporarily sees all tools until revert.

### T13.2.3 — feat(puppeteer_mcp): add in-memory sliding-window rate limiter (REQ-PMCP-4)

- **Files**: `app/core/puppeteer_mcp.py` (+40)
- **Action**: `_RATE_LIMIT: dict[int, list[float]] = {}` (key = `user_id`, value = timestamps in epoch seconds); `_check_rate_limit(user_id) -> None` raises `PuppeteerUnavailable(reason="puppeteer_rate_limited")` when ≥ `PUPPETEER_RENDER_RATE_LIMIT_PER_MINUTE` (default 5) timestamps fall within the last 60 s; helper prunes the window on every check. **Single-replica only** — resets on backend restart (R-SPEC-4 mitigation documented in ADR-013 §Security).
- **RED test** (lands in T13.4.1): `freezegun`-driven test — 5 calls in 60 s succeed, 6th raises `PuppeteerUnavailable(reason="puppeteer_rate_limited")`; window-pruning after 61 s resets.
- **Commit**: `feat(puppeteer_mcp): add in-memory sliding-window rate limiter`
- **Risk**: medium. Rollback: remove `_RATE_LIMIT` and `_check_rate_limit` calls; renders proceed without limit until revert.

### T13.2.4 — feat(db): migration 0009_add_message_attachments.sql + schema.sql mirror (REQ-EM-DELTA-1)

- **Files**: `migrations/0009_add_message_attachments.sql` (NEW, ~5); `schema.sql` (+1)
- **Action**: idempotent `ALTER TABLE messages ADD COLUMN IF NOT EXISTS attachments JSONB NOT NULL DEFAULT '[]'::jsonb;` mirrored verbatim into `schema.sql` immediately after the `CREATE TABLE messages` block.
- **Test** (lands in T13.4.4): re-run `python migrations/run_migrations.py` against a fresh SQLite-in-memory DB; re-run against an existing DB (idempotent).
- **Commit**: `feat(db): migration 0009_add_message_attachments.sql + schema.sql mirror`
- **Risk**: low. Rollback: `ALTER TABLE messages DROP COLUMN IF EXISTS attachments;` (reversible per design §11).

### T13.2.5 — feat(models): Message.attachments JSONB column

- **Files**: `app/models/message.py` (+5)
- **Action**: new column `attachments = Column(JSON().with_variant(JSONB(), "postgresql"), nullable=False, server_default=text("'[]'"))` mirroring the `citations` precedent at lines 58–62. `app/models/__init__.py` UNCHANGED (no new ORM class).
- **Test** (lands in T13.4.4): `tests/core/test_message_store.py` extended with `Message(...).attachments == []` after a fresh save.
- **Commit**: `feat(models): add attachments JSONB column to Message`
- **Risk**: low. Rollback: drop the column block; existing tests still pass.

### T13.2.6 — feat(message_store): save_attachment + list_attachments + save_message attachments kwarg (REQ-ATT-1)

- **Files**: `app/core/message_store.py` (+40)
- **Action**: `save_attachment(db, message_id, kind, mime, storage_path, source_url, bytes) -> dict` returns a typed `Attachment` dict (no ORM); mutates `Message.attachments = (Message.attachments or []) + [att]` then `db.flush()`. `list_attachments(db, message_id) -> list[dict]`. `save_message()` signature gains `attachments: list[dict] | None = None` and merges them into the row's JSONB column inside the same flush. `_coerce_attachments(...)` mirrors `_coerce_citations(...)` at lines 37–50.
- **Test** (lands in T13.4.4): `tests/core/test_message_store.py` extension — `save_message(..., attachments=[att])` lands JSONB; `list_attachments(...)` round-trips.
- **Commit**: `feat(message_store): save_attachment + list_attachments + save_message attachments kwarg`
- **Risk**: medium. Rollback: drop the new helpers; revert the `save_message` kwarg; `_persist_turn` callers (T13.2.9) will need a follow-up.

### T13.2.7 — feat(attachment_tokens): sign_attachment_token / verify_attachment_token / _ensure_uploads_dir (REQ-ATT-2)

- **Files**: `app/core/attachment_tokens.py` (NEW, ~40)
- **Action**: `sign_attachment_token(attachment_id: str, user_id: int, ttl: int = 300) -> str` + `verify_attachment_token(token, attachment_id, user_id) -> bool` via `itsdangerous.URLSafeTimedSerializer`; key = `hashlib.sha256(JWT_SECRET_KEY.encode()).digest()`; salt = `b"attachment-token"`. `_ensure_uploads_dir()` creates `/app/uploads/screenshots/` (idempotent `os.makedirs(..., exist_ok=True)`).
- **Call site for `_ensure_uploads_dir`**: lazy from `app/api/attachments.py:get_attachment` first call (avoids the design drift on `app/main.py:on_startup` — `server.py` has no lifespan hook today; lazy call keeps `server.py` untouched).
- **RED test** (lands in T13.4.2): sign + verify happy path; expired token (>5 min via `freezegun`); tampered payload (HMAC mismatch); cross-attachment-id reuse rejected.
- **Commit**: `feat(attachment_tokens): sign/verify helpers + uploads-dir bootstrap`
- **Risk**: medium (auth). Rollback: `rm app/core/attachment_tokens.py`.

### T13.2.8 — feat(agent): compose context7_tools + puppeteer_tools + DIAGRAM_HINT (REQ-PMCP-1, REQ-PMCP-5)

- **Files**: `app/core/agent.py` (+30)
- **Action**: new sibling `_try_get_puppeteer_tools()` mirroring `_try_get_context7_tools()` at lines 190–211 (returns `([], degraded_dict)` on `PuppeteerUnavailable`); compose `tools = context7_tools + puppeteer_tools` inside `run_agent` after the `_has_architect_pattern` short-circuit (line 326) and before `build_agent` (line 340); on `PuppeteerUnavailable` yield exactly one `degraded` event with `source="puppeteer"` and the right `reason`. New constant `DIAGRAM_HINT: str = (...)` appended after `LIBRARY_HINT` (line 40); `_build_system_prompt` (line 113) appends `DIAGRAM_HINT` to the prompt after `LIBRARY_HINT`.
- **RED test** (lands in T13.4.4): `tests/api/test_chat.py` SCN-PMCP-1 mock — `run_agent` yields exactly one `attachment` SSE event when the agent emits a Mermaid block + Langfuse handler receives a tool span automatically (REQ-PMCP-5 — covered by existing F11 mocks; new assertion only).
- **Commit**: `feat(agent): compose context7_tools + puppeteer_tools; add DIAGRAM_HINT`
- **Risk**: medium (system-prompt + tool surface). Rollback: revert `tools = context7_tools + puppeteer_tools` to `tools = context7_tools`; drop the `DIAGRAM_HINT` line from `_build_system_prompt`.

### T13.2.9 — feat(chat): persist attachments in same transaction + emit event: attachment SSE (REQ-ATT-1, REQ-PMCP-1)

- **Files**: `app/api/chat.py` (+60)
- **Action**: `_persist_turn` (lines 232–267) extended: accepts `attachments: list[dict] | None`; after the `asst_msg = save_message(...)` call, for each attachment append to `asst_msg.attachments` via the `save_message(attachments=...)` kwarg (T13.2.6) and `db.flush()` inside the SAME pre-`done` transaction. SSE `event_generator` (lines 280–313) gains one new `if event_name == "attachment":` branch that serialises `{kind, mime, url, filename}` — strips `storage_path` (server-only). `_patch_chat_route` collaborators gain `save_attachment` mock (forwarded to T13.4.4). Yield contract extended — agents yield `{"event": "attachment", "data": {...}}` between the last `token` and `done`.
- **RED test** (lands in T13.4.4): SCN-ATT-1 — simulated `SQLAlchemyError` on `save_message(assistant)` rolls back attachment rows; SCN-ATT-2 — attachment row alone fails rolls back message; SCN-PMCP-1 — when `run_agent` yields an `attachment` event, route persists + emits `event: attachment` with `url` containing a non-empty `token=`.
- **Commit**: `feat(chat): persist attachments in pre-done transaction; emit event: attachment SSE`
- **Risk**: high (transactional seam). Rollback: revert the diff; `_persist_turn` returns to F12 behaviour; SSE strips the new branch.

### T13.2.10 — feat(attachments): GET /api/chat/attachments/{id} route (REQ-ATT-2, REQ-ATT-3)

- **Files**: `app/api/attachments.py` (NEW, ~80); `app/api/__init__.py` (+2) to register the router; `server.py` (+1) to `include_router(attachments_router)`.
- **Action**: `GET /api/chat/attachments/{id}` — (1) read `?token=`, call `verify_attachment_token(token, id, user_id)` → `HTTPException(401)` on miss; (2) look up `Message` by id whose `attachments` JSONB contains the id AND cross-checks `(user_id, project_id)` ownership → `HTTPException(404)` on miss (defense in depth); (3) `FileResponse(path, media_type=att["mime"], headers={"Content-Disposition": f'inline; filename="{att["filename"]}"', "Cache-Control": "private, max-age=300"})`. **No WARNING logs on these paths** (avoid info-leak; mirrors `chat_history` posture).
- **RED test** (lands in T13.4.3): 401 missing token, 401 expired, 401 forged, 404 cross-user, 404 unknown id, 200 happy path with `Content-Type: image/png` + `Content-Disposition: inline; filename="diagram-12345.png"` (SCN-ATT-6).
- **Commit**: `feat(attachments): GET /api/chat/attachments/{id} with signed-token auth`
- **Risk**: medium. Rollback: `rm app/api/attachments.py`; revert `server.py` `include_router` line.

**Phase 2 end-of-phase verification**: `docker compose exec backend pytest tests/core/test_message_store.py tests/core/test_attachment_tokens.py tests/api/test_attachments.py tests/api/test_chat.py -q` → all green. `curl http://localhost:8000/api/chat` smoke test (with `PUPPETEER_RENDER_RATE_LIMIT_PER_MINUTE=0` per design §7 Phase 1) returns one `event: degraded` with `reason="puppeteer_rate_limited"`.

---

## 5. Phase 3 — Frontend (~180 LoC)

**Deployable checkpoint**: full user-visible flow — assistant emits a Mermaid block, the chat shows the rendered `<img>` inline below the source code, the URL carries a signed token.

### T13.3.1 — feat(frontend/api/chat): extend dispatchSSEEvent for event: attachment + onAttachment callback + history parsing

- **Files**: `frontend/src/api/chat.ts` (+20)
- **Action**: `StreamCallbacks` interface gains `onAttachment?: (att: {kind: 'screenshot'; mime: 'image/png'; url: string; filename: string}) => void`. `dispatchSSEEvent` (lines 38–87) handles `event: attachment` → calls `callbacks.onAttachment?.(JSON.parse(rawData))`. `ChatHistoryMessage` interface gains `attachments?: Attachment[]`; `fetchChatHistory` parses it (+10 inside the same file).
- **Commit**: `feat(frontend/api): handle event: attachment SSE + parse history attachments`
- **Risk**: low. Rollback: revert the `dispatchSSEEvent` branch + `ChatHistoryMessage` field.

### T13.3.2 — feat(frontend/stores): Message.attachments? + sendMessage onAttachment wiring

- **Files**: `frontend/src/stores/chatStore.ts` (+30)
- **Action**: `Message` interface gains `attachments?: Attachment[]` where `Attachment = {kind: 'screenshot'; mime: 'image/png'; url: string; filename: string}`. `sendMessage` (lines 44–107) passes `onAttachment` callback that appends to the in-flight assistant message's `attachments` list via `state.messages.map(...)`. `loadHistory` (lines 166–187) propagates attachments from the history payload.
- **Commit**: `feat(frontend/stores): Message.attachments? + onAttachment SSE wiring`
- **Risk**: low. Rollback: revert the field + the `onAttachment` callback argument.

### T13.3.3 — feat(frontend/components): render inline <img> in MessageBubble

- **Files**: `frontend/src/components/MessageBubble.tsx` (+15)
- **Action**: inside the assistant `<div>` (line 333–342), after `renderMarkdownBlocks(message.content)`, render `<img src={a.url} alt={a.filename} className="max-w-md rounded-lg my-2" loading="lazy" />` for each attachment with `kind === "screenshot"`. **No download button in v1** (Q-NEW-DOWNLOAD-PNG deferred per design §8).
- **Commit**: `feat(frontend/components): render inline <img> for screenshot attachments`
- **Risk**: low. Rollback: revert the `<img>` map block.

### T13.3.4 — feat(frontend/components): pass onAttachment callback in ChatWindow

- **Files**: `frontend/src/components/ChatWindow.tsx` (+5)
- **Action**: thread the `onAttachment` callback from the chat store into `createChatStream` (the function `sendMessage` invokes). One prop + one line.
- **Commit**: `feat(frontend/components): thread onAttachment callback through ChatWindow`
- **Risk**: low. Rollback: revert the prop + the one line.

### T13.3.5 — test(frontend/components): MessageBubble.test.tsx (NEW) — empty/one/user attachments

- **Files**: `frontend/src/components/__tests__/MessageBubble.test.tsx` (NEW, ~60)
- **Action**: render `<MessageBubble role="assistant" content="..." attachments={...} />` in three flavours — empty `attachments` (no `<img>` rendered), one attachment (one `<img>` with `src` matching the signed URL + `alt` matching filename), and a user message (no attachments slot — the `<img>` map only fires when `role === "assistant"`).
- **Commit**: `test(frontend/components): MessageBubble renders attachments correctly`
- **Risk**: low. Rollback: `rm` the file.

**Phase 3 end-of-phase verification**: `cd frontend && pnpm vitest run src/components/__tests__/MessageBubble.test.tsx src/stores/__tests__/chatStore.test.ts` → all green. Manual smoke: open the SPA, prompt "diagram a C4 component graph", verify the `<img>` renders with a valid signed URL.

---

## 6. Phase 4 — Tests + ADR + docs (~155 LoC tests, ~150 LoC ADR)

**Deployable checkpoint**: full pytest + vitest suites green. ADR-013 records the security posture. `apply-progress` entry recorded for the archive.

### T13.4.1 — test(puppeteer_mcp): transport, allow-list, timeout, byte cap, rate-limit (REQ-PMCP-2..4)

- **Files**: `tests/core/test_puppeteer_mcp.py` (NEW, ~150)
- **Action**: mirror `tests/core/test_context7_mcp.py`. Coverage:
  - `test_build_puppeteer_client_*` (3 tests) — `PUPPETEER_MCP_URL` read at call time, `transport="streamable_http"` literal, `timeout=30.0` default.
  - `test_allow_list_filter` (REQ-PMCP-2 SCN-PMCP-3) — recorded fixture of 8 upstream tools → output is exactly `["puppeteer_screenshot"]`.
  - `test_timeout_raises_puppeteer_unavailable` (SCN-PMCP-4) — `asyncio.wait_for` patched to `TimeoutError` → `PuppeteerUnavailable(reason="puppeteer_timeout")`.
  - `test_byte_cap_rejects_large_response` (SCN-PMCP-5) — mock client returning a 3 MB payload → `PuppeteerUnavailable(reason="puppeteer_byte_cap")`.
  - `test_rate_limit_5_per_minute` (SCN-PMCP-6) — `freezegun` 6 calls in 60 s → 6th raises `PuppeteerUnavailable(reason="puppeteer_rate_limited")`; window prune after 61 s.
  - `test_reset_client_for_tests` — singleton teardown.
- **Commit**: `test(puppeteer_mcp): transport, allow-list, timeout, byte cap, rate-limit`
- **Risk**: low. Rollback: `rm` the file.

### T13.4.2 — test(attachment_tokens): sign/verify happy + expired + tampered + cross-id (REQ-ATT-2)

- **Files**: `tests/core/test_attachment_tokens.py` (NEW, ~50)
- **Action**: coverage:
  - `test_sign_and_verify_happy_path` — round-trip succeeds.
  - `test_verify_expired_token` (SCN-ATT-5) — `freezegun.time_to_freeze` advance 301 s → returns `False`.
  - `test_verify_tampered_payload` (SCN-ATT-5) — flip one char of the token → returns `False`.
  - `test_verify_cross_attachment_id_rejected` — sign for id `A`, verify with id `B` → `False`.
  - `test_ensure_uploads_dir_idempotent` — second call is a no-op.
- **Commit**: `test(attachment_tokens): sign/verify edge cases + uploads-dir idempotency`
- **Risk**: low. Rollback: `rm` the file.

### T13.4.3 — test(attachments): 401/404/200 + cross-user + Content-Disposition (REQ-ATT-2, REQ-ATT-3, SCN-ATT-3..6)

- **Files**: `tests/api/test_attachments.py` (NEW, ~120)
- **Action**: mirror `tests/api/test_chat_history.py`. Coverage:
  - `test_200_owned_attachment` (SCN-ATT-3) — `Content-Type: image/png` + bytes match.
  - `test_404_cross_user` (SCN-ATT-4) — user B requests user A's attachment → 404, not 403.
  - `test_404_unknown_id` — random UUID → 404.
  - `test_401_missing_token` (SCN-ATT-5) — `?token=` absent → 401.
  - `test_401_expired_token` (SCN-ATT-5) — `freezegun` advance 6 min → 401.
  - `test_401_forged_token` (SCN-ATT-5) — tampered token → 401.
  - `test_200_content_disposition_inline` (SCN-ATT-6) — `Content-Disposition: inline; filename="diagram-12345.png"`.
  - `test_404_no_warning_log` — assert no WARNING-level log line (info-leak posture).
- **Commit**: `test(attachments): 401/404/200 + cross-user + token-expiry`
- **Risk**: low. Rollback: `rm` the file.

### T13.4.4 — test(chat): persistence + event: attachment SSE + atomic rollback (REQ-PMCP-1, REQ-ATT-1)

- **Files**: `tests/api/test_chat.py` (+30); `tests/core/test_message_store.py` (+20 — extensions land in T13.4.6 implicitly through this commit).
- **Action**: extend `_patch_chat_route` (lines 198–262) to mock `save_attachment` + `save_message(attachments=...)`. New SCN coverage:
  - `test_run_agent_yields_attachment_event_then_done` (SCN-PMCP-1) — `run_agent` yields `{"event": "attachment", "data": {...}}` between last `token` and `done`; SSE bytes contain `event: attachment` + `url=/api/chat/attachments/<uuid>?token=...`.
  - `test_no_attachment_event_when_no_mermaid_block` (SCN-PMCP-2) — zero `attachment` events.
  - `test_atomic_persist_message_and_attachments` (SCN-ATT-1) — `save_message(assistant)` raises `SQLAlchemyError` → attachment rows also rolled back.
  - `test_atomic_rollback_when_attachment_fails` (SCN-ATT-2) — attachment insert fails → message row also rolled back → subsequent `list_attachments(message_id=...)` returns `[]`.
  - `test_langfuse_span_for_puppeteer_tool` (REQ-PMCP-5) — using existing F11 Langfuse mocks, assert the tool call name `puppeteer_screenshot` appears in the captured spans.
- **Commit**: `test(chat): persistence + event:attachment SSE + atomic rollback`
- **Risk**: low. Rollback: revert the SCN additions.

### T13.4.5 — test(frontend/stores): chatStore onAttachment appends to in-flight message

- **Files**: `frontend/src/stores/__tests__/chatStore.test.ts` (+30)
- **Action**: extend the existing test file with one new test — mock `createChatStream` to call the `onAttachment` callback mid-stream with a sample attachment; assert the in-flight assistant message's `attachments` array receives the entry. One additional test — `loadHistory` populates `attachments` from the history payload.
- **Commit**: `test(frontend/stores): chatStore onAttachment wiring`
- **Risk**: low. Rollback: revert the additions.

### T13.4.6 — docs(adr): 013-puppeteer-mcp.md (ADR-013)

- **Files**: `docs/adr/013-puppeteer-mcp.md` (NEW, ~150)
- **Action**: record — (a) sidecar + `streamable_http` over in-container stdio (image-bloat avoidance); (b) tool-surface filter as a hard invariant (only `puppeteer_screenshot` reaches the LLM); (c) per-call 15 s timeout + 2 MB byte cap; (d) per-user 5/min in-memory rate limit (R-SPEC-4 — single-replica); (e) signed query-string token (TTL 5 min) via `itsdangerous.URLSafeTimedSerializer`; (f) persistent browser per container (warm on start); (g) `mem_limit: 512m` on the sidecar; (h) JSONB column → table migration path on `docs/adr/013-puppeteer-mcp.md §Storage`.
- **Commit**: `docs(adr): 013-puppeteer-mcp sidecar + security posture`
- **Risk**: low. Rollback: `rm` the file.

**Phase 4 end-of-phase verification**: `docker compose exec backend pytest tests/ -q` → all green (F11 + F12 + F13); `cd frontend && pnpm vitest run` → all green.

---

## 7. Test strategy (per phase)

| Phase | New tests | Test command | Expected result |
|---|---|---|---|
| 1 | None (no Python imports yet) | `docker compose build puppeteer-mcp` | image builds (~600 MB) |
| 1 | Smoke check | `docker compose up -d puppeteer-mcp && docker compose exec puppeteer-mcp wget --spider http://localhost:8931/health` | exit 0 |
| 2 | Tests live with green tasks (T13.2.1, T13.2.2, T13.2.3, T13.2.4, T13.2.6, T13.2.7, T13.2.9, T13.2.10) — pytest green at end of Phase 2 | `docker compose exec backend pytest tests/core/test_puppeteer_mcp.py tests/core/test_attachment_tokens.py tests/api/test_attachments.py tests/api/test_chat.py tests/core/test_message_store.py tests/test_engram_client.py -q` | all green |
| 3 | `frontend/src/components/__tests__/MessageBubble.test.tsx` (NEW) + extensions to `frontend/src/stores/__tests__/chatStore.test.ts` | `cd frontend && pnpm vitest run src/components/__tests__/MessageBubble.test.tsx src/stores/__tests__/chatStore.test.ts` | all green |
| 4 | Final acceptance: full pytest + full vitest | `docker compose exec backend pytest tests/ -q` AND `cd frontend && pnpm vitest run` | all green |

### Spec REQ → test file coverage matrix

| Spec REQ | Test files |
|---|---|
| REQ-PMCP-1 (render + emit `event: attachment` before `done`) | `tests/api/test_chat.py` (T13.4.4 SCN-PMCP-1) |
| REQ-PMCP-2 (positive allow-list; `puppeteer_navigate` absent) | `tests/core/test_puppeteer_mcp.py::test_allow_list_filter` (T13.4.1) |
| REQ-PMCP-3 (15s timeout + 2MB byte cap) | `tests/core/test_puppeteer_mcp.py` (T13.4.1) |
| REQ-PMCP-4 (5/min rate limit → `degraded`) | `tests/core/test_puppeteer_mcp.py` (T13.4.1) |
| REQ-PMCP-5 (Langfuse span automatic) | `tests/api/test_chat.py` (T13.4.4 SCN-PMCP-7 — assertion only, no new tracer code) |
| REQ-ATT-1 (atomic persist; rollback on either-side fail) | `tests/api/test_chat.py` (T13.4.4 SCN-ATT-1, SCN-ATT-2) |
| REQ-ATT-2 (signed-token auth + 401/404 semantics) | `tests/api/test_attachments.py` + `tests/core/test_attachment_tokens.py` (T13.4.3, T13.4.2) |
| REQ-ATT-3 (Content-Type + Content-Disposition from row) | `tests/api/test_attachments.py` (T13.4.3 SCN-ATT-3, SCN-ATT-6) |
| REQ-EM-DELTA-1 (`attachments JSONB` column) | `tests/test_schema_sync.py` extension (F12 backlog) + `tests/core/test_message_store.py` (T13.4.4) + `tests/api/test_chat.py` (T13.4.4) |

---

## 8. Work-unit commit map (17 commits, ≤ 200 LoC each)

| # | Commit | LoC | Type | Scope | Files | Rollback boundary |
|---|---|---|---|---|---|---|
| 1 | `chore(deps): add itsdangerous==2.1.2` | +1 | chore | deps | `requirements.txt` | drop the line; nothing else imports it yet |
| 2 | `chore(infra): add puppeteer-mcp sidecar Dockerfile + entrypoint` | +45 | chore | infra | `infrastructure/puppeteer-mcp/{Dockerfile,entrypoint.sh,.dockerignore}` | `rm -rf infrastructure/puppeteer-mcp/`; compose in commit 3 references it |
| 3 | `chore(compose): wire puppeteer-mcp service + healthcheck` | +25 | chore | compose | `docker-compose.yml` | revert the service block + backend `depends_on` line |
| 4 | `chore(env): add PUPPETEER_* vars to .env.example` | +4 | chore | env | `.env.example` | delete the 4 lines |
| 5 | `feat(puppeteer_mcp): scaffold client + PuppeteerUnavailable + reset_client_for_tests` | +70 | feat | puppeteer_mcp | `app/core/puppeteer_mcp.py` | `rm app/core/puppeteer_mcp.py` |
| 6 | `feat(puppeteer_mcp): add positive tool allow-list filter` | +30 | feat | puppeteer_mcp | `app/core/puppeteer_mcp.py` | drop the filter line; keep the helper |
| 7 | `feat(puppeteer_mcp): add in-memory sliding-window rate limiter` | +40 | feat | puppeteer_mcp | `app/core/puppeteer_mcp.py` | remove `_RATE_LIMIT` + `_check_rate_limit` calls |
| 8 | `feat(db): migration 0009_add_message_attachments.sql + schema.sql mirror` | +6 | feat | db | `migrations/0009_add_message_attachments.sql`, `schema.sql` | `ALTER TABLE messages DROP COLUMN IF EXISTS attachments` |
| 9 | `feat(models): add attachments JSONB column to Message` | +5 | feat | models | `app/models/message.py` | drop the column block |
| 10 | `feat(message_store): save_attachment + list_attachments + save_message attachments kwarg` | +40 | feat | message_store | `app/core/message_store.py` | drop the new helpers + `save_message` kwarg |
| 11 | `feat(attachment_tokens): sign/verify helpers + uploads-dir bootstrap` | +40 | feat | attachment_tokens | `app/core/attachment_tokens.py` | `rm app/core/attachment_tokens.py` |
| 12 | `feat(agent): compose context7_tools + puppeteer_tools; add DIAGRAM_HINT` | +30 | feat | agent | `app/core/agent.py` | revert `tools = context7_tools + puppeteer_tools` to F11 + drop `DIAGRAM_HINT` |
| 13 | `feat(chat): persist attachments in pre-done transaction; emit event: attachment SSE` | +60 | feat | chat | `app/api/chat.py` | revert `_persist_turn` + drop the new SSE branch |
| 14 | `feat(attachments): GET /api/chat/attachments/{id} with signed-token auth` | +83 | feat | attachments | `app/api/attachments.py`, `app/api/__init__.py`, `server.py` | `rm app/api/attachments.py`; revert router include |
| 15 | `feat(frontend): dispatchSSEEvent + chatStore Message.attachments? + MessageBubble inline <img>` | +180 | feat | frontend | `frontend/src/api/chat.ts`, `frontend/src/stores/chatStore.ts`, `frontend/src/components/MessageBubble.tsx`, `frontend/src/components/ChatWindow.tsx` | revert each file to its pre-F13 state |
| 16 | `test(puppeteer_mcp,attachment_tokens,attachments,chat): red-tests + extensions` (composite; splits below if budget blows past 200) | +370 | test | tests | `tests/core/test_puppeteer_mcp.py`, `tests/core/test_attachment_tokens.py`, `tests/api/test_attachments.py`, `tests/api/test_chat.py`, `tests/core/test_message_store.py`, `frontend/src/components/__tests__/MessageBubble.test.tsx`, `frontend/src/stores/__tests__/chatStore.test.ts` | `rm` each new file; revert the chat/test_message_store extensions |
| 17 | `docs(adr): 013-puppeteer-mcp sidecar + security posture` | +150 | docs | adr | `docs/adr/013-puppeteer-mcp.md` | `rm` the file |

**Splitting rule for commit 16**: if pre-commit `git diff --stat` shows > 200 changed lines, split into 16a (`test(puppeteer_mcp): ...`), 16b (`test(attachment_tokens,attachments): ...`), 16c (`test(chat): ...`), 16d (`test(frontend): ...`) — the work-unit-commits skill rule "≤ 200 LoC per commit where possible" wins. Each split commit still carries tests with their behaviour because Phase 2 already landed the green tasks 5–14 that the tests verify.

**Phase ↔ commit mapping**:
- Phase 1 → commits 1–4
- Phase 2 → commits 5–14 (10 commits; the user-listed sequence maps 1:1; commits 8 and 9 are the design-driven split of "feat(db)" + "feat(models)" that the user's 8th commit absorbed — splitting honours the "Keep tests with code" rule and keeps each ≤ 50 LoC).
- Phase 3 → commit 15
- Phase 4 → commits 16 + 17

---

## 9. Review Workload Forecast

```
Review Workload Forecast
========================
Total changed lines (estimate): 1,155 (backend 540 + frontend 180 + tests 350 + docs 150 - 65 overlap)
  Breakdown by file:
    app/core/puppeteer_mcp.py (NEW): 200
    app/core/attachment_tokens.py (NEW): 40
    app/core/agent.py: +30
    app/core/message_store.py: +40
    app/models/message.py: +5
    app/api/chat.py: +60
    app/api/attachments.py (NEW): 80
    app/api/__init__.py: +2
    server.py: +1
    migrations/0009_add_message_attachments.sql (NEW): 5
    schema.sql: +1
    infrastructure/puppeteer-mcp/Dockerfile (NEW): 30
    infrastructure/puppeteer-mcp/entrypoint.sh (NEW): 10
    infrastructure/puppeteer-mcp/.dockerignore (NEW): 5
    docker-compose.yml: +25
    .env.example: +4
    requirements.txt: +1
    frontend/src/api/chat.ts: +30
    frontend/src/stores/chatStore.ts: +30
    frontend/src/components/MessageBubble.tsx: +15
    frontend/src/components/ChatWindow.tsx: +5
    frontend/src/components/__tests__/MessageBubble.test.tsx (NEW): 60
    frontend/src/stores/__tests__/chatStore.test.ts: +30
    tests/core/test_puppeteer_mcp.py (NEW): 150
    tests/core/test_attachment_tokens.py (NEW): 50
    tests/api/test_attachments.py (NEW): 120
    tests/api/test_chat.py: +30
    tests/core/test_message_store.py: +20
    docs/adr/013-puppeteer-mcp.md (NEW): 150
Decision needed before apply: No (size:exception approved by user this session)
Chained PRs recommended: No (single-pr with size:exception approved)
400-line budget risk: High (mitigated by size:exception)
Chain strategy: size-exception
Reviewer burden per commit: ≤ 200 LoC each (work-unit-commits respected; commit 16 may split into 16a–16d per splitting rule)
```

---

## 10. Open questions — Deferred (do not reopen in tasks)

- **Q-NEW-DOWNLOAD-PNG** — spec-deferred; design marks an OPTIONAL 5-LoC `MessageBubble.tsx` "Save" button as future work (out of scope for F13 tasks).
- **Q-NEW-AUTOSCROLL** — frontend-only decision (does new `<img>` trigger `ChatWindow` autoscroll?); out of OpenSpec scope; deferred.
- **Q-NEW-RATE-LIMIT-STORAGE** — design RESOLVED to in-memory `dict[user_id, list[float]]` for MVP; promote to Redis in F14 if horizontal scaling arrives. Documented as R-SPEC-4 mitigation in ADR-013 §Security (T13.4.6).
- **Q2 Mermaid-only** — LOCKED by proposal + both new specs' §Scope Confirmation; F13 ships Mermaid-only; arbitrary HTML rendering is OUT of scope (F14).

No NEW open questions surfaced during task planning. The `_ensure_uploads_dir()` lazy call from `app/api/attachments.py` (T13.2.7) replaces the design's `app/main.py:on_startup` reference — `server.py` has no lifespan hook today; lazy invocation keeps `server.py` untouched and is the minimum-coupling path. This is a **design drift documented in the task**, not a re-opening of a deferred question.

---

## 11. References

- `openspec/changes/2026-09-07-F13-puppeteer-mcp/explore.md` — 10 risks, 3 alternatives, 10 open questions resolved
- `openspec/changes/2026-09-07-F13-puppeteer-mcp/proposal.md` — 10 resolved ambiguities, 8 risks, rollback plan
- `openspec/changes/2026-09-07-F13-puppeteer-mcp/design.md` — file-by-file inventory, test plan, rollout (§7)
- `openspec/specs/puppeteer-mcp-integration/spec.md` — REQ-PMCP-1..5, SCN-PMCP-1..7
- `openspec/specs/chat-attachments/spec.md` — REQ-ATT-1..3, SCN-ATT-1..6
- `openspec/specs/engram-conversation-memory/spec.md` — DELTA-1 (`attachments JSONB`)
- `app/core/context7_mcp.py:1-221` — F11 `MultiServerMCPClient` pattern mirrored verbatim by `puppeteer_mcp.py`
- `app/core/agent.py:113-115, 190-211, 326-340` — system-prompt seam, `_try_get_context7_tools` sibling, `run_agent` tool-composition seam
- `app/api/chat.py:232-267, 280-313` — `_persist_turn` pre-`done` transaction + SSE `event_generator` seams extended
- `app/core/message_store.py:37-50, 81-102` — `_coerce_citations` + `save_message(citations=...)` precedent for `attachments`
- `app/models/message.py:58-62` — `citations` JSONB column precedent for `attachments`
- `migrations/0008_add_messages_table.sql` — F12 migration pattern mirrored by `0009`
- `tests/api/test_chat.py:198-262` — `_patch_chat_route` convention extended
- `docs/adr/007-six-mcps.md:78` — names the Puppeteer package (`@modelcontextprotocol/server-puppeteer`); F13 implements.
- `docs/adr/010-context7-agent-runtime.md` — F11's `MultiServerMCPClient` runtime precedent.
- `docs/adr/011-engram-conversation-mirror.md` — F12's persistence seam; F13 sits next to it.
- Issue #17 — [F13] Puppeteer MCP integrado (acceptance criteria).

(End of file — 25 tasks across 4 phases; 17 work-unit commits; ~1,155 prod LoC + ~350 test LoC + ~150 docs LoC.)
