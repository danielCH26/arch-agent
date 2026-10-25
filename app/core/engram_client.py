"""Cliente mínimo para la API HTTP local de Engram."""

import json
import os
from typing import Any
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class EngramError(RuntimeError):
    """Engram no está disponible o devolvió una respuesta inválida."""


class EngramClient:
    def __init__(self, base_url: str | None = None, timeout: float = 3.0):
        self.base_url = (base_url or os.getenv("ENGRAM_URL", "http://localhost:7437")).rstrip("/")
        self.timeout = timeout

    def create_session(self, session_id: str, project: str, directory: str) -> None:
        self._request("POST", "/sessions", {"id": session_id, "project": project, "directory": directory})

    def end_session(self, session_id: str, summary: str) -> None:
        self._request("POST", f"/sessions/{session_id}/end", {"summary": summary})

    def save_observation(
        self, session_id: str, project: str, title: str, content: str, observation_type: str = "discovery"
    ) -> None:
        self._request(
            "POST",
            "/observations",
            {
                "session_id": session_id,
                "type": observation_type,
                "title": title,
                "content": content,
                "project": project,
                "scope": "project",
            },
        )

    def get_context(self, project: str) -> str:
        response = self._request("GET", f"/context?{urlencode({'project': project, 'scope': 'project'})}")
        if isinstance(response, dict):
            return str(response.get("context", ""))
        return ""

    # ------------------------------------------------------------------
    # F12 extensions (REQ-5): retrieval-side methods. Existing methods
    # above are unchanged so ADR-005 / ADR-011 callers stay intact.
    # ------------------------------------------------------------------

    def search(
        self,
        scope: str,
        query: str,
        project: str | None,
        user_id: int | None = None,
        limit: int = 10,
    ) -> list[dict]:
        """Search observations scoped to ``project`` + ``user_id``.

        Defensive: ``project`` is REQUIRED (REQ-5 / SCN-6). A missing
        ``project`` raises ``ValueError`` immediately so a caller that
        forgot to scope the call cannot accidentally leak across users.
        """
        if not project:
            raise ValueError("project is required")

        params: dict[str, Any] = {
            "scope": scope,
            "project": project,
            "query": query,
            "limit": limit,
        }
        if user_id is not None:
            params["user_id"] = user_id

        response = self._request("GET", f"/observations?{urlencode(params)}")
        if isinstance(response, dict):
            return list(response.get("observations") or response.get("results") or [])
        if isinstance(response, list):
            return response
        return []

    def get_observation(self, observation_id: int) -> dict:
        """Fetch a single observation by id. Raises ``EngramError`` on miss."""
        response = self._request("GET", f"/observations/{observation_id}")
        if isinstance(response, dict):
            return response
        return {}

    def save(
        self,
        topic_key: str,
        content: str,
        *,
        title: str = "",
        observation_type: str = "chat_message",
        project: str | None = None,
        scope: str = "project",
        session_id: str | None = None,
    ) -> dict:
        """Fire-and-forget sibling observation (REQ-6 / ADR-011).

        ``session_id`` MUST reference a session already registered via
        ``create_session`` — Engram's ``/observations`` FK is strict and
        rejects an unregistered explicit ``session_id`` with 400 (verified
        against the real server, not just the mocked test contract).
        ``topic_key`` is a *separate*, optional upsert/dedup key — it does
        NOT satisfy the session FK on its own.

        Returns the parsed JSON response (typically ``{"id": <int>}``).
        The chat route catches ``EngramError`` and continues without
        surfacing the failure to the SSE stream (REQ-6, REQ-10).
        """
        body: dict[str, Any] = {
            "topic_key": topic_key,
            "content": content,
            "title": title,
            "type": observation_type,
            "scope": scope,
        }
        if project is not None:
            body["project"] = project
        if session_id is not None:
            body["session_id"] = session_id
        response = self._request("POST", "/observations", body)
        return response if isinstance(response, dict) else {}

    def delete(self, observation_id: int) -> None:
        """Best-effort delete of an observation. Used by retention jobs."""
        self._request("DELETE", f"/observations/{observation_id}")

    def _request(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = Request(
            f"{self.base_url}{path}",
            data=data,
            method=method,
            headers={"Content-Type": "application/json"} if data else {},
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                payload = response.read().decode("utf-8")
        except (URLError, OSError) as exc:
            raise EngramError(f"No fue posible conectar con Engram: {exc}") from exc

        try:
            return json.loads(payload) if payload else {}
        except json.JSONDecodeError as exc:
            raise EngramError("Engram devolvió una respuesta que no es JSON.") from exc