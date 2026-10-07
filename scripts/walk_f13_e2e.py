#!/usr/bin/env python3
"""End-to-end walk for PR #104 / F13: Puppeteer MCP diagram rendering.

Drives the REAL backend over HTTP with a REAL tool-calling LLM (Groq
``openai/gpt-oss-120b`` by default, or a local Ollama model) and asserts the
full acceptance criterion: a chat turn that asks for a Mermaid diagram
streams back an ``event: attachment`` whose signed URL serves a real PNG.

Run it against an ISOLATED stack started from ``docker-compose.walk.yml``
(see that file) so a live default-port stack is never touched:

    docker compose -f docker-compose.yml -f docker-compose.walk.yml \
        -p walk-f13 up -d --build

    WALK_USERNAME=walk_user WALK_PASSWORD='WalkF13!pass' \
    WALK_LLM_API_KEY=gsk_... python3 scripts/walk_f13_e2e.py

Re-run only the chat step against an existing user + project:

    WALK_USERNAME=walk_user WALK_PASSWORD='WalkF13!pass' \
    WALK_PROJECT_ID=3 python3 scripts/walk_f13_e2e.py --skip-until-chat

Contracts implemented here (extracted from tests + app code, not invented):

- Health:        there is NO dedicated /health route in the backend
                 (server.py registers only routers + /register HTML form);
                 the walk probes FastAPI's built-in ``GET /openapi.json``.
- Auth:          POST /api/auth/register {username, email, password} -> 201
                 {user_id, username, token}; 409 when already exists
                 (app/api/auth.py:67). POST /api/auth/login {username,
                 password} -> 200 {user_id, username, token}
                 (app/api/auth.py:82). Password policy: >= 8 chars, upper,
                 digit, special (app/auth/validators.py:32).
- LLM wizard:    POST /api/llm/wizard/step1 {base_url} pings
                 ``GET {base_url}/models`` WITHOUT auth from the backend
                 container and accepts 200/401/403 (app/api/llm_config.py,
                 wizard_step1). NOTE: for Ollama this hits the provider, so
                 the URL must be reachable from inside the backend container
                 (e.g. http://host.docker.internal:11434/v1 on Docker
                 Desktop, or your host IP on Linux). step2 {base_url,
                 api_key} pings /models WITH Bearer and requires 200.
                 step3 {base_url, model, allow_unknown_model} persists the
                 model; the DB is the source of truth (body base_url/api_key
                 are ignored, app/api/llm_config.py wizard_step3) and
                 ``allow_unknown_model=true`` is needed for models absent
                 from app/core/llm_model_benchmarks.yaml (e.g.
                 openai/gpt-oss-120b), otherwise 400.
- Projects:      POST /api/projects {name, description?} -> 201
                 {id, current_phase: "requerimientos", ...}; 409 on
                 duplicate name (app/api/projects.py:103).
                 GET  /api/projects/{id}/phase -> {current_phase,
                 phase_ready, available_phases} (app/api/projects.py:189).
                 POST /api/projects/{id}/advance -> advances one phase,
                 requires phase_ready=true (app/api/projects.py:203).
- Elicitation:   POST /api/projects/{id}/elicitation/message with {} returns
                 the deterministic FIRST_QUESTION without any LLM call; with
                 {"answer": "..."} it appends the answer and calls the LLM.
                 Response: {done, question, resumen, history}
                 (app/api/elicitation.py:117). Loop rules live server-side
                 in app/core/elicitation_agent.py: MIN_QUESTIONS=5,
                 MAX_QUESTIONS=10 (done is forced at 10, blocked before 5).
                 POST /api/projects/{id}/elicitation/decision
                 {"decision": "approve"} -> {decision, phase_ready, message}
                 (app/api/elicitation.py:238).
- Proposal:      POST /api/proposals/generate {project_id} -> SSE
                 sources -> token* -> done{"proposal_id", "citations"}
                 (app/core/proposal_generator.py generate_stream; error
                 event on failure). POST /api/proposals/{id}/decide
                 {"decision": "approve"} -> {proposal_id, lifecycle:
                 "approved", current_phase, phase_ready}
                 (app/api/proposals.py:318).
- Phase guard:   /api/chat has NO phase guard — only 400 empty message,
                 401 bad JWT, 403/404 project ownership, 409 LLM not
                 configured, 503 DB down (app/api/chat.py chat()). No
                 advance is required to chat after the proposal approval.
- Chat:          POST /api/chat {project_id, message} -> text/event-stream.
                 Events in order: sources, (tool_start/tool_end)*, token*,
                 [degraded], [attachment*], done; error is terminal
                 (app/api/chat.py event_generator). The ``attachment``
                 payload is {id, kind, mime, url, filename} where ``url``
                 is a RELATIVE signed URL
                 ``/api/chat/attachments/{id}?token=...`` built by
                 app/core/attachment_tokens.py build_attachment_url; the
                 signed token TTL is 300s. A diagram turn is triggered when
                 the message matches \\b(diagrama|diagram|mermaid|flowchart|
                 graph)\\b or the phase is a diagram phase
                 (app/api/chat.py _is_diagram_turn).
- Attachment:    GET /api/chat/attachments/{id}?token=... requires the
                 signed query token and NO Authorization header (that is the
                 whole point of signed URLs); serves the PNG bytes with
                 401/404 on failure (app/api/attachments.py get_attachment).

Stdlib only (urllib/json/argparse) so it runs on any Python 3.11+ without a
venv. The API key is read from the environment and NEVER printed; JWTs are
redacted to their first 8 characters.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
MIN_PNG_BYTES = 10 * 1024  # signed-URL payload must be a real screenshot

DEFAULT_BASE_URL = "http://localhost:18000"
DEFAULT_LLM_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_LLM_MODEL = "openai/gpt-oss-120b"

# Message guaranteed to match _DIAGRAM_REQUEST_PATTERN ("diagrama", "mermaid")
# so the agent reaches for the puppeteer_screenshot tool (F13).
DIAGRAM_PROMPT = (
    "Haz un diagrama mermaid de flujo para un checkout de e-commerce"
)

# Short realistic answers for the elicitation loop. The server enforces
# MIN_QUESTIONS=5 / MAX_QUESTIONS=10 (app/core/elicitation_agent.py:25), so
# at least 5 rounds happen even if the model wants to stop earlier.
ELICITATION_ANSWERS = [
    "Es un checkout de e-commerce: el cliente arma un carrito, paga con "
    "tarjeta o transferencia y recibe una confirmacion por email.",
    "Lo usan clientes finales que compran y un operador de soporte que "
    "revisa pagos fallidos y reintentos.",
    "Debe integrar la pasarela de pago, calcular impuestos y enviar el "
    "email de confirmacion con el detalle del pedido.",
    "Esperamos hasta 500 usuarios concurrentes y respuestas de menos de "
    "2 segundos en el flujo de pago.",
    "Hay que guardar el historial de pedidos y cumplir PCI-DSS para los "
    "datos de tarjeta; no guardamos datos sensibles en texto plano.",
    "Sin mas restricciones: empezar con el alcance minimo y crecer por "
    "iteraciones.",
]


def redact(secret: str) -> str:
    """First 8 chars + '...' — never log a full credential."""
    if not secret:
        return "<empty>"
    return secret[:8] + "..."


class StepFailure(Exception):
    """Raised by a step when it cannot continue; message is user-facing."""


# ---------------------------------------------------------------------------
# HTTP helpers (stdlib only)
# ---------------------------------------------------------------------------


def http_request(
    method: str,
    url: str,
    *,
    body: dict | None = None,
    token: str | None = None,
    timeout: float = 180.0,
):
    """JSON request -> (status, parsed_body) or raise StepFailure.

    Non-2xx responses are returned as (status, body) so callers decide how
    to tolerate them (e.g. 409 already-exists on register).
    """
    headers = {"Accept": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
        try:
            parsed = json.loads(raw) if raw else None
        except ValueError:
            parsed = raw
        return resp.status, parsed
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            parsed = json.loads(raw) if raw else None
        except ValueError:
            parsed = raw
        return exc.code, parsed
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise StepFailure(f"{method} {url} failed: {exc}") from exc


def open_sse_stream(
    method: str,
    url: str,
    *,
    body: dict,
    token: str,
    timeout: float = 180.0,
):
    """Open an SSE POST and return the raw line-iterable response."""
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "Authorization": f"Bearer {token}",
        },
        method=method,
    )
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise StepFailure(f"{method} {url} -> HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise StepFailure(f"{method} {url} failed: {exc}") from exc


def iter_sse_events(resp):
    """Yield (event_name, raw_data) for each SSE frame in the stream."""
    event_name: str | None = None
    data_lines: list[str] = []
    for raw in resp:
        line = raw.decode("utf-8", "replace").rstrip("\r\n")
        if line == "":
            if event_name is not None or data_lines:
                yield event_name or "message", "\n".join(data_lines)
            event_name, data_lines = None, []
            continue
        if line.startswith("event:"):
            event_name = line[len("event:"):].strip()
        elif line.startswith("data:"):
            data_lines.append(line[len("data:"):].strip())
    if event_name is not None or data_lines:
        yield event_name or "message", "\n".join(data_lines)


def sse_data_json(raw: str):
    try:
        return json.loads(raw)
    except ValueError:
        return raw


# ---------------------------------------------------------------------------
# Steps — each returns a short OK detail or raises StepFailure(reason)
# ---------------------------------------------------------------------------


def step_health(cfg) -> str:
    # No /health route exists; /openapi.json is FastAPI's built-in liveness
    # surface and needs no auth.
    status, body = http_request("GET", f"{cfg.base_url}/openapi.json",
                                timeout=cfg.step_timeout)
    if status != 200:
        raise StepFailure(f"GET /openapi.json -> HTTP {status}")
    title = body.get("info", {}).get("title") if isinstance(body, dict) else None
    return f"HTTP 200, api={title!r}"


def step_register_and_login(cfg) -> str:
    payload = {
        "username": cfg.username,
        "email": f"{cfg.username}@walk.local",
        "password": cfg.password,
    }
    status, body = http_request("POST", f"{cfg.base_url}/api/auth/register",
                                body=payload, timeout=cfg.step_timeout)
    if status == 201:
        reg_note = "registered"
    elif status == 409:
        reg_note = "already exists (tolerated)"
    else:
        raise StepFailure(f"register -> HTTP {status}: {body}")

    status, body = http_request("POST", f"{cfg.base_url}/api/auth/login",
                                body={"username": cfg.username,
                                      "password": cfg.password},
                                timeout=cfg.step_timeout)
    if status != 200 or not isinstance(body, dict) or not body.get("token"):
        raise StepFailure(f"login -> HTTP {status}: {body}")
    cfg.token = body["token"]
    return f"{reg_note}, logged in (token {redact(cfg.token)})"


def step_configure_llm(cfg) -> str:
    details = []
    # Step 1: validates base_url by pinging GET {base}/models WITHOUT auth
    # from the backend container (200/401/403 OK). Ollama users: this hits
    # the provider, so the URL must be reachable from inside the container;
    # if your Ollama is not reachable from Docker, skip this step's failure
    # by configuring the LLM manually in the UI and re-running with
    # --skip-until-chat.
    status, body = http_request("POST", f"{cfg.base_url}/api/llm/wizard/step1",
                                body={"base_url": cfg.llm_base_url},
                                token=cfg.token, timeout=cfg.step_timeout)
    if status != 200 or not (isinstance(body, dict) and body.get("success")):
        raise StepFailure(
            f"wizard/step1 -> HTTP {status}: {body} "
            f"(provider {cfg.llm_base_url}/models must be reachable from "
            f"INSIDE the backend container; local Ollama may need "
            f"host.docker.internal or --skip-until-chat)"
        )
    details.append("step1 base_url OK")

    # Step 2: pings /models WITH Bearer; requires 200 (key must be valid).
    status, body = http_request("POST", f"{cfg.base_url}/api/llm/wizard/step2",
                                body={"base_url": cfg.llm_base_url,
                                      "api_key": cfg.llm_api_key},
                                token=cfg.token, timeout=cfg.step_timeout)
    if status != 200 or not (isinstance(body, dict) and body.get("success")):
        raise StepFailure(f"wizard/step2 -> HTTP {status}: {body}")
    details.append("step2 api_key stored")

    # Step 3: persists the model. Body base_url/api_key are ignored by the
    # backend (DB is source of truth). allow_unknown_model=true is required
    # for models not in llm_model_benchmarks.yaml (e.g. openai/gpt-oss-120b),
    # otherwise the endpoint answers 400 "no esta en tier 1".
    status, body = http_request("POST", f"{cfg.base_url}/api/llm/wizard/step3",
                                body={"base_url": cfg.llm_base_url,
                                      "api_key": cfg.llm_api_key,
                                      "model": cfg.llm_model,
                                      "allow_unknown_model": True},
                                token=cfg.token, timeout=cfg.step_timeout)
    if status != 200 or not (isinstance(body, dict) and body.get("success")):
        raise StepFailure(f"wizard/step3 -> HTTP {status}: {body}")
    details.append(f"step3 model={cfg.llm_model} stored")
    return "; ".join(details)


def step_create_project(cfg) -> str:
    cfg.project_name = f"F13 Walk {time.strftime('%Y%m%d-%H%M%S')}"
    status, body = http_request(
        "POST", f"{cfg.base_url}/api/projects",
        body={
            "name": cfg.project_name,
            "description": (
                "Proyecto efimero del walk E2E de F13: render de diagramas "
                "con Puppeteer MCP (PR #104)."
            ),
        },
        token=cfg.token, timeout=cfg.step_timeout,
    )
    if status != 201 or not isinstance(body, dict):
        raise StepFailure(f"create project -> HTTP {status}: {body}")
    cfg.project_id = int(body["id"])
    phase = body.get("current_phase")
    if phase != "requerimientos":
        raise StepFailure(
            f"new project should start in 'requerimientos', got {phase!r}"
        )
    return f"project id={cfg.project_id} phase={phase}"


def step_elicitation(cfg) -> str:
    base = f"{cfg.base_url}/api/projects/{cfg.project_id}/elicitation"

    # First call carries NO answer -> deterministic FIRST_QUESTION, no LLM.
    status, body = http_request("POST", f"{base}/message", body={},
                                token=cfg.token, timeout=cfg.step_timeout)
    if status != 200 or not isinstance(body, dict):
        raise StepFailure(f"elicitation start -> HTTP {status}: {body}")
    question = body.get("question")
    turns = 0

    for answer in ELICITATION_ANSWERS:
        if body.get("done") or body.get("resumen"):
            break
        if not question:
            raise StepFailure(
                f"elicitation stalled: no pending question after {turns} turns"
            )
        turns += 1
        status, body = http_request("POST", f"{base}/message",
                                    body={"answer": answer},
                                    token=cfg.token, timeout=cfg.step_timeout)
        if status != 200 or not isinstance(body, dict):
            raise StepFailure(f"elicitation answer #{turns} -> "
                              f"HTTP {status}: {body}")
        question = body.get("question")

    if not body.get("done") or not body.get("resumen"):
        # Server enforces MAX_QUESTIONS=10; more than 12 loops means the
        # model never converged and the walk cannot proceed.
        raise StepFailure(
            f"elicitation did not finish after {turns} answers "
            f"(server caps at MAX_QUESTIONS=10)"
        )

    resumen_chars = len(json.dumps(body["resumen"], ensure_ascii=False))
    status, body = http_request("POST", f"{base}/decision",
                                body={"decision": "approve"},
                                token=cfg.token, timeout=cfg.step_timeout)
    if status != 200 or not isinstance(body, dict) or not body.get("phase_ready"):
        raise StepFailure(f"elicitation decision -> HTTP {status}: {body}")
    return f"{turns} Q&A rounds, resumen {resumen_chars} chars, approved"


def step_generate_and_approve_proposal(cfg) -> str:
    resp = open_sse_stream(
        "POST", f"{cfg.base_url}/api/proposals/generate",
        body={"project_id": cfg.project_id},
        token=cfg.token, timeout=cfg.step_timeout,
    )
    proposal_id: int | None = None
    token_count = 0
    error_payload = None
    with resp:
        for event_name, raw in iter_sse_events(resp):
            if event_name == "token":
                token_count += 1
            elif event_name == "done":
                payload = sse_data_json(raw)
                if isinstance(payload, dict):
                    proposal_id = payload.get("proposal_id")
                break
            elif event_name == "error":
                error_payload = sse_data_json(raw)
                break
    if error_payload is not None:
        raise StepFailure(f"generate SSE error: {error_payload}")
    if proposal_id is None:
        raise StepFailure(
            f"generate stream ended without done/proposal_id "
            f"({token_count} tokens)"
        )

    status, body = http_request(
        "POST", f"{cfg.base_url}/api/proposals/{proposal_id}/decide",
        body={"decision": "approve"}, token=cfg.token,
        timeout=cfg.step_timeout,
    )
    if status != 200 or not isinstance(body, dict) \
            or body.get("lifecycle") != "approved":
        raise StepFailure(f"decide -> HTTP {status}: {body}")
    return (f"proposal id={proposal_id} ({token_count} SSE tokens), "
            f"lifecycle=approved")


def step_phase_check(cfg) -> str:
    """/api/chat has NO phase guard (app/api/chat.py chat(): 400/401/403/404/
    409/503 only), so no advance is strictly required. We still advance
    requerimientos -> propuesta when eligible, because that mirrors the real
    HU flow and keeps the approved proposal semantically in its phase."""
    status, body = http_request(
        "GET", f"{cfg.base_url}/api/projects/{cfg.project_id}/phase",
        token=cfg.token, timeout=cfg.step_timeout,
    )
    if status != 200 or not isinstance(body, dict):
        raise StepFailure(f"GET phase -> HTTP {status}: {body}")
    phase, ready = body.get("current_phase"), body.get("phase_ready")
    advanced = False
    if phase == "requerimientos" and ready:
        status, body = http_request(
            "POST", f"{cfg.base_url}/api/projects/{cfg.project_id}/advance",
            token=cfg.token, timeout=cfg.step_timeout,
        )
        if status == 200 and isinstance(body, dict):
            phase = body.get("current_phase", phase)
            advanced = True
    return f"phase={phase} (advance={'yes' if advanced else 'not needed — chat has no phase guard'})"


def step_chat_diagram(cfg) -> str:
    resp = open_sse_stream(
        "POST", f"{cfg.base_url}/api/chat",
        body={"project_id": cfg.project_id, "message": DIAGRAM_PROMPT},
        token=cfg.token, timeout=cfg.step_timeout,
    )
    tokens: list[str] = []
    degraded: list = []
    attachments: list[dict] = []
    tool_events = 0
    done_seen = False
    error_payload = None
    with resp:
        for event_name, raw in iter_sse_events(resp):
            if event_name == "token":
                payload = sse_data_json(raw)
                if payload:
                    tokens.append(str(payload))
            elif event_name == "degraded":
                degraded.append(sse_data_json(raw))
            elif event_name == "attachment":
                payload = sse_data_json(raw)
                if isinstance(payload, dict):
                    attachments.append(payload)
            elif event_name in ("tool_start", "tool_end"):
                tool_events += 1
            elif event_name == "done":
                done_seen = True
                break
            elif event_name == "error":
                error_payload = sse_data_json(raw)
                break
    if error_payload is not None:
        raise StepFailure(f"chat SSE error: {error_payload}")
    if not done_seen:
        raise StepFailure("chat stream ended without event: done")
    if not attachments:
        raise StepFailure(
            "no event: attachment arrived — the agent never called "
            "puppeteer_screenshot (is PUPPETEER_MCP_URL up? is the model a "
            "tool-calling model?)"
        )
    att = attachments[0]
    if not att.get("id") or not att.get("url"):
        raise StepFailure(f"attachment payload missing id/url: keys="
                          f"{sorted(att.keys())}")
    cfg.attachment_url = att["url"]
    cfg.attachment_id = att["id"]
    notes = [
        f"{len(tokens)} tokens, {tool_events} tool events",
        f"{len(attachments)} attachment(s)",
    ]
    if degraded:
        notes.append(f"degraded={degraded} (Context7 unavailable — tolerated)")
    return ", ".join(notes)


def step_fetch_attachment(cfg) -> str:
    url = cfg.attachment_url
    if not url.startswith("http"):
        url = f"{cfg.base_url}{url}"
    # Deliberately NO Authorization header: the signed ?token= query param is
    # the whole auth mechanism for <img> tags (app/api/attachments.py).
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=cfg.step_timeout) as resp:
            status = resp.status
            payload = resp.read()
    except urllib.error.HTTPError as exc:
        raise StepFailure(f"GET attachment -> HTTP {exc.code} "
                          f"(signed token expired? TTL is 300s)") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise StepFailure(f"GET attachment failed: {exc}") from exc

    if status != 200:
        raise StepFailure(f"GET attachment -> HTTP {status}")
    if not payload.startswith(PNG_MAGIC):
        raise StepFailure(
            f"body does not start with PNG magic bytes "
            f"(first bytes: {payload[:8]!r})"
        )
    size = len(payload)
    if size <= MIN_PNG_BYTES:
        raise StepFailure(f"PNG too small: {size} bytes (need > {MIN_PNG_BYTES})")
    return (f"attachment id={cfg.attachment_id}, HTTP 200, PNG magic OK, "
            f"{size} bytes")


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


class Config:
    def __init__(self, args) -> None:
        self.base_url = os.environ.get("WALK_BASE_URL",
                                       DEFAULT_BASE_URL).rstrip("/")
        self.username = os.environ.get("WALK_USERNAME", "")
        self.password = os.environ.get("WALK_PASSWORD", "")
        self.llm_base_url = os.environ.get("WALK_LLM_BASE_URL",
                                           DEFAULT_LLM_BASE_URL)
        self.llm_api_key = os.environ.get("WALK_LLM_API_KEY", "")
        self.llm_model = os.environ.get("WALK_LLM_MODEL", DEFAULT_LLM_MODEL)
        self.project_id_env = os.environ.get("WALK_PROJECT_ID", "")
        self.step_timeout = args.step_timeout
        self.skip_until_chat = args.skip_until_chat

        self.token = ""
        self.project_id: int | None = None
        self.project_name = ""
        self.attachment_url = ""
        self.attachment_id = ""

    def validate_env(self) -> None:
        missing = [name for name, value in (
            ("WALK_USERNAME", self.username),
            ("WALK_PASSWORD", self.password),
        ) if not value]
        if self.skip_until_chat:
            if not self.project_id_env:
                missing.append("WALK_PROJECT_ID (required with --skip-until-chat)")
        elif not self.llm_api_key:
            missing.append("WALK_LLM_API_KEY")
        if missing:
            raise SystemExit(
                "Missing required environment variables: " + ", ".join(missing)
            )
        if self.project_id_env:
            self.project_id = int(self.project_id_env)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="F13 E2E walk: Puppeteer MCP diagram rendering (PR #104).",
    )
    parser.add_argument(
        "--step-timeout", type=float, default=180.0,
        help="per-request timeout in seconds (LLM steps are slow; default 180)",
    )
    parser.add_argument(
        "--skip-until-chat",
        action="store_true",
        help="skip register/wizard/project/elicitation/proposal and go "
             "straight to the chat step (re-runs; needs WALK_PROJECT_ID)",
    )
    cfg = Config(parser.parse_args())
    cfg.validate_env()

    print(f"F13 walk -> {cfg.base_url} | user={cfg.username} | "
          f"llm={cfg.llm_model} @ {cfg.llm_base_url} | "
          f"api_key={redact(cfg.llm_api_key)}")
    if cfg.skip_until_chat:
        steps = [
            ("health", step_health),
            ("login", step_register_and_login),
            ("chat-diagram", step_chat_diagram),
            ("fetch-attachment", step_fetch_attachment),
        ]
    else:
        steps = [
            ("health", step_health),
            ("register+login", step_register_and_login),
            ("configure-llm", step_configure_llm),
            ("create-project", step_create_project),
            ("elicitation", step_elicitation),
            ("proposal", step_generate_and_approve_proposal),
            ("phase-check", step_phase_check),
            ("chat-diagram", step_chat_diagram),
            ("fetch-attachment", step_fetch_attachment),
        ]

    total = len(steps)
    ok_count = 0
    for index, (name, fn) in enumerate(steps, start=1):
        try:
            detail = fn(cfg)
        except StepFailure as exc:
            reason = str(exc)
            print(f"[{index}/{total}] {name}: FAIL {reason}")
            print(f"WALK F13: FAIL (step {index}: {reason})")
            return 1
        except Exception as exc:  # noqa: BLE001 — walk must never crash raw
            reason = f"unexpected {type(exc).__name__}: {exc}"
            print(f"[{index}/{total}] {name}: FAIL {reason}")
            print(f"WALK F13: FAIL (step {index}: {reason})")
            return 1
        ok_count += 1
        print(f"[{index}/{total}] {name}: OK {detail}")

    print(f"WALK F13: PASS ({ok_count} steps ok)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
