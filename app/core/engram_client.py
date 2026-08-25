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
