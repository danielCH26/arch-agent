#!/usr/bin/env python3
"""Walk E2E de HU10 (staged approvals, issue #21) contra el stack aislado.

Ejecuta el flujo completo de fases como lo vive un usuario real, sin
mocks, y verifica tanto el camino feliz como los gates negativos:

    requerimientos: elicitacion -> approve -> advance
    propuesta:      generate propuesta -> approve (+ idempotencia)
    refinamiento:   modify (con feedback) -> pending no nulo (B4)
                    -> advance bloqueado (409) -> approve -> advance
    revision:       reject -> pending no nulo (B4) -> approve -> advance
    final:          modify rechazado (I3/REQ-SA-8) -> approve -> advance
                    bloqueado (ultima fase)

Gates negativos pinchados: phase_mismatch (409), advance sin aprovacion
(409/400), modify en final (400), advance en final (400).

Uso (con el stack de docker-compose.walk.yml):

    export WALK_LLM_API_KEY=gsk_...          # requerida; NUNCA se imprime
    python3 scripts/walk_hu10_e2e.py

Credenciales y endpoints por entorno (WALK_*); re-corrida del bloque de
fases contra un proyecto existente con WALK_PROJECT_ID + --skip-until-phases.

Salida: [i/N] paso: OK/FAIL detalle; linea final "WALK HU10: PASS/FAIL";
exit 0/1. Los tokens se loggean truncados; la API key jamas.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any, Optional

import httpx

DEFAULT_LLM_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_LLM_MODEL = "openai/gpt-oss-120b"  # requiere allow_unknown_model=true
STEP_TIMEOUT = float(os.environ.get("WALK_STEP_TIMEOUT", "180"))
_HU10_PHASES = ("propuesta", "refinamiento", "revision", "final")


def _redact(token: str) -> str:
    return (token[:8] + "...") if token else "<empty>"


class Walk:
    def __init__(self) -> None:
        self.base_url = os.environ.get("WALK_BASE_URL", "http://localhost:18000").rstrip("/")
        self.username = os.environ.get("WALK_USERNAME", "walk_hu10_user")
        self.password = os.environ.get("WALK_PASSWORD", "WalkHu10!pass")
        self.llm_base_url = os.environ.get("WALK_LLM_BASE_URL", DEFAULT_LLM_BASE_URL)
        self.llm_api_key = os.environ.get("WALK_LLM_API_KEY", "")
        self.llm_model = os.environ.get("WALK_LLM_MODEL", DEFAULT_LLM_MODEL)
        self.project_id_env = os.environ.get("WALK_PROJECT_ID", "")
        self.token: str = ""
        self.project_id: Optional[int] = None
        self.client = httpx.Client(timeout=STEP_TIMEOUT)
        self.total = 0

    # -- infrastructura de pasos ------------------------------------------

    def step(self, ok: bool, detail: str) -> None:
        self.total += 1
        mark = "OK" if ok else "FAIL"
        print(f"[{self.total}] {detail}: {mark}" if ok else f"[{self.total}] {detail}: {mark}")
        if not ok:
            raise StepFailure(detail)

    def info(self, msg: str) -> None:
        print(f"    {msg}")

    # -- helpers HTTP -------------------------------------------------------

    def _headers(self) -> dict:
        h = {"Authorization": f"Bearer {self.token}"}
        return h

    def req(self, method: str, path: str, *, json_body: Any = None,
            expect: tuple = (200,), auth: bool = True) -> httpx.Response:
        r = self.client.request(
            method,
            f"{self.base_url}{path}",
            json=json_body,
            headers=self._headers() if auth else {},
        )
        if r.status_code not in expect:
            body = r.text[:300]
            raise StepFailure(
                f"{method} {path} -> {r.status_code} (esperaba {expect}): {body}"
            )
        return r

    def sse_done_payload(self, method: str, path: str, json_body: Any) -> dict:
        """Lee un stream SSE y devuelve el payload del evento `done`."""
        done_payload: Optional[dict] = None
        with self.client.stream(
            "POST", f"{self.base_url}{path}", json=json_body,
            headers=self._headers(), timeout=STEP_TIMEOUT,
        ) as r:
            if r.status_code != 200:
                raise StepFailure(f"SSE {path} -> {r.status_code}: {r.read()[:300]!r}")
            event = ""
            for line in r.iter_lines():
                if line.startswith("event: "):
                    event = line[len("event: "):].strip()
                elif line.startswith("data: ") and event == "done":
                    done_payload = json.loads(line[len("data: "):])
                    break
                elif line.startswith("data: ") and event == "error":
                    raise StepFailure(f"SSE {path} -> error: {line[:300]}")
        if done_payload is None:
            raise StepFailure(f"SSE {path} termino sin evento done")
        return done_payload


class StepFailure(Exception):
    pass


# ---------------------------------------------------------------------------
# Pasos
# ---------------------------------------------------------------------------

def step_health(w: Walk) -> None:
    r = w.client.get(f"{w.base_url}/openapi.json")
    w.step(r.status_code == 200, "health (openapi.json)")


def step_register_login(w: Walk) -> None:
    r = w.client.post(
        f"{w.base_url}/api/auth/register",
        json={
            "username": w.username,
            "email": f"{w.username}@walk.local",
            "password": w.password,
        },
    )
    if r.status_code not in (200, 201, 409):
        raise StepFailure(f"register -> {r.status_code}: {r.text[:300]}")
    if r.status_code == 409:
        w.info("usuario ya existia (409) — continúo con login")

    r = w.client.post(
        f"{w.base_url}/api/auth/login",
        json={"username": w.username, "password": w.password},
    )
    if r.status_code != 200:
        raise StepFailure(f"login -> {r.status_code}: {r.text[:300]}")
    w.token = r.json()["token"]
    w.step(True, f"register+login (token {_redact(w.token)})")


def step_wizard(w: Walk) -> None:
    if not w.llm_api_key:
        raise StepFailure(
            "WALK_LLM_API_KEY no está seteada (la key NUNCA se imprime)"
        )
    r = w.req("POST", "/api/llm/wizard/step1",
              json_body={"base_url": w.llm_base_url}, expect=(200,))
    r = w.req("POST", "/api/llm/wizard/step2",
              json_body={"base_url": w.llm_base_url, "api_key": w.llm_api_key},
              expect=(200,))
    # gpt-oss-120b no figura en llm_model_benchmarks.yaml -> tier unknown ->
    # sin allow_unknown_model el wizard responde 400.
    r = w.req("POST", "/api/llm/wizard/step3",
              json_body={
                  "base_url": w.llm_base_url,
                  "model": w.llm_model,
                  "allow_unknown_model": True,
              }, expect=(200,))
    w.step(r.status_code == 200, f"wizard (model={w.llm_model})")


def step_create_project(w: Walk) -> None:
    if w.project_id_env:
        w.project_id = int(w.project_id_env)
        w.step(True, f"proyecto reusado por WALK_PROJECT_ID={w.project_id}")
        return
    r = w.req("POST", "/api/projects",
              json_body={"name": "Walk HU10", "description": "walk e2e"},
              expect=(200, 201))
    w.project_id = int(r.json()["id"])
    w.step(True, f"crear proyecto id={w.project_id} (fase requerimientos)")


def _pending(w: Walk) -> Optional[dict]:
    r = w.req("GET", f"/api/projects/{w.project_id}/phases")
    return r.json().get("pending_decision")


def step_elicitation(w: Walk) -> None:
    """Recorre la elicitacion (MIN 5 preguntas) y aprueba el resumen."""
    turns = 0
    while True:
        r = w.req("POST", f"/api/projects/{w.project_id}/elicitation/message",
                  json_body={}, expect=(200,))
        data = r.json()
        history_len = len(data.get("history") or [])
        if data.get("done"):
            break
        if history_len >= 5:
            # MIN_QUESTIONS alcanzado: la siguiente decision approve es valida.
            break
        turns += 1
        if turns > 10:
            raise StepFailure("elicitacion excedio 10 turnos sin done")
        r = w.req("POST", f"/api/projects/{w.project_id}/elicitation/message",
                  json_body={"answer": "Un sistema interno para un equipo chico, "
                                      "sin requerimientos exoticos de performance."},
                  expect=(200,))
        if r.json().get("done"):
            break
    r = w.req("POST", f"/api/projects/{w.project_id}/elicitation/decision",
              json_body={"decision": "approve"}, expect=(200,))
    w.step(True, f"elicitacion ({turns} respuestas) -> approve")


def step_advance(w: Walk, from_phase: str, to_phase: str) -> None:
    r = w.req("POST", f"/api/projects/{w.project_id}/advance", expect=(200,))
    w.step(True, f"advance {from_phase} -> {to_phase}")


def step_decision(w: Walk, phase: str, action: str,
                  feedback: Optional[str] = None) -> dict:
    body: dict = {"action": action}
    if feedback is not None:
        body["feedback"] = feedback
    r = w.req("POST", f"/api/projects/{w.project_id}/phase/{phase}/decision",
              json_body=body, expect=(200,))
    return r.json()


def step_neg_decision_mismatch(w: Walk) -> None:
    """Decidir una fase que NO es la actual -> 409 phase_mismatch."""
    r = w.client.post(
        f"{w.base_url}/api/projects/{w.project_id}/phase/revision/decision",
        json={"action": "approve"}, headers=w._headers(),
    )
    ok = r.status_code == 409
    err = ""
    try:
        err = r.json().get("detail", {}).get("error", "")
    except Exception:
        pass
    ok = ok and err == "phase_mismatch"
    w.step(ok, f"gate: decision fuera de fase -> 409 phase_mismatch (got {r.status_code}/{err or '?'})")


def step_neg_advance_blocked(w: Walk, expect_statuses: tuple = (400, 409)) -> None:
    """Advance con la fase sin aprobar -> 409 phase_not_approved (HU10)
    o 400 (phase_ready false en F05)."""
    r = w.client.post(
        f"{w.base_url}/api/projects/{w.project_id}/advance",
        headers=w._headers(),
    )
    w.step(r.status_code in expect_statuses,
           f"gate: advance sin aprovacion -> {r.status_code} (esperaba {expect_statuses})")


def step_neg_modify_final(w: Walk) -> None:
    """modify en final -> 400 (REQ-SA-8/I3, gate en record_decision)."""
    r = w.client.post(
        f"{w.base_url}/api/projects/{w.project_id}/phase/final/decision",
        json={"action": "modify", "feedback": "un ajuste"},
        headers=w._headers(),
    )
    w.step(r.status_code == 400,
           f"gate: modify en final -> 400 (got {r.status_code})")


def step_neg_advance_final(w: Walk) -> None:
    """advance en final -> 400 (ultima fase)."""
    r = w.client.post(
        f"{w.base_url}/api/projects/{w.project_id}/advance",
        headers=w._headers(),
    )
    ok = r.status_code == 400
    w.step(ok, f"gate: advance en final -> 400 ultima fase (got {r.status_code})")


# ---------------------------------------------------------------------------
# Flujo principal
# ---------------------------------------------------------------------------

def run(w: Walk, skip_until_phases: bool) -> None:
    step_health(w)
    step_register_login(w)
    step_wizard(w)
    step_create_project(w)

    if not skip_until_phases:
        step_elicitation(w)
        # requerimientos es F05-owned: approve -> phase_ready -> advance.
        step_advance(w, "requerimientos", "propuesta")

    # ---- propuesta (HU10-owned) -----------------------------------------
    step_neg_decision_mismatch(w)
    done = w.sse_done_payload(
        "POST", "/api/proposals/generate", {"project_id": w.project_id}
    )
    proposal_id = done.get("proposal_id")
    w.step(proposal_id is not None, f"generar propuesta id={proposal_id}")

    first = step_decision(w, "propuesta", "approve")
    w.step(first.get("phase_ready") is True, "aprobar propuesta -> phase_ready true")
    # Idempotencia (REQ-SA-30.1): retry identico dentro de la ventana.
    retry = step_decision(w, "propuesta", "approve")
    w.step(retry.get("idempotent") is True, "retry identico -> idempotent=true")
    step_advance(w, "propuesta", "refinamiento")

    # ---- refinamiento: modify -> pending no nulo (B4) --------------------
    step_decision(w, "refinamiento", "modify",
                  feedback="Falta el modulo de notificaciones")
    pend = _pending(w)
    w.step(pend is not None,
           "despues de modify: pending_decision no nulo (B4)")
    step_neg_advance_blocked(w)
    step_decision(w, "refinamiento", "approve")
    w.step(_pending(w) is None,
           "despues de approve: pending_decision nulo")
    step_advance(w, "refinamiento", "revision")

    # ---- revision: reject -> pending no nulo -> approve -------------------
    step_decision(w, "revision", "reject")
    pend = _pending(w)
    w.step(pend is not None and pend.get("last_decision") == "rejected",
           "approve->reject: pending no nulo con last_decision=rejected (B4)")
    step_decision(w, "revision", "approve")
    step_advance(w, "revision", "final")

    # ---- final: gates + cierre --------------------------------------------
    step_neg_modify_final(w)
    step_decision(w, "final", "approve")
    step_neg_advance_final(w)


def main() -> int:
    ap = argparse.ArgumentParser(description="Walk E2E de HU10 (staged approvals)")
    ap.add_argument("--skip-until-phases", action="store_true",
                    help="omite register/wizard/proyecto/elicitacion y arranca "
                         "en propuesta (requiere WALK_PROJECT_ID)")
    args = ap.parse_args()

    w = Walk()
    print(f"Walk HU10 contra {w.base_url} (usuario {w.username}, "
          f"model {w.llm_model})")
    try:
        run(w, skip_until_phases=args.skip_until_phases)
    except StepFailure as e:
        print(f"WALK HU10: FAIL ({e})")
        return 1
    except httpx.HTTPError as e:
        print(f"WALK HU10: FAIL (HTTP: {e})")
        return 1
    print(f"WALK HU10: PASS ({w.total} checks)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
