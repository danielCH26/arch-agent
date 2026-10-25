import asyncio
import json
import time
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler


# REQ-7: tool result payloads are capped at this byte length on the SSE wire.
# ADR-010 §"Precedencia RAG ↔ Context7" — keeps the on-wire size bounded for
# small local models and for Chainlit's console logging.
_TOOL_RESULT_MAX_BYTES: int = 4000


class SSEStreamCallbackHandler(BaseCallbackHandler):
    """
    LangChain callback handler that collects LLM tokens and tool events and
    makes them available as an async iterator for FastAPI's StreamingResponse.

    Usage:
        handler = SSEStreamCallbackHandler()
        agent.invoke({"input": msg}, {"callbacks": [handler]})
        async for event in handler:
            yield event

    Event payloads (already serialized as ``data: <json>\n\n``):

        token     : ``"<chunk>"``                          (str)
        tool_start: ``{"tool": "<name>"}``                  (REQ-7)
        tool_end  : ``{"tool": "<name>", "result_length": N,
                        "latency_ms": M, "status": "ok"|"error"}``
        done      : ``null``                                 (last on success)
        error     : ``"<message>"``                          (last on failure)
    """

    def __init__(self):
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._done = False
        self._errors: list[str] = []

        # Tool-event latency accounting. ``_tool_started_at`` is keyed by
        # ``run_id`` so concurrent tools do not collide; ``_tool_name`` maps
        # the same run_id back to the user-visible tool name.
        self._tool_started_at: dict[str, float] = {}
        self._tool_name: dict[str, str] = {}

    # ------------------------------------------------------------------
    # LLM token streaming (F08 surface — preserved byte-for-byte)
    # ------------------------------------------------------------------

    async def on_llm_new_token(self, token: str, **kwargs: Any) -> None:
        """Called by LangChain each time a new token arrives."""
        if token:
            await self._queue.put(_format_sse_event("token", token))

    def on_llm_end(self, *args: Any, **kwargs: Any) -> None:
        self._done = True

    def on_llm_error(self, error: Exception, **kwargs: Any) -> None:
        self._errors.append(str(error))
        self._done = True

    # ------------------------------------------------------------------
    # Tool event streaming (REQ-7 / F11)
    # ------------------------------------------------------------------

    async def on_tool_start(
        self,
        serialized: dict[str, Any] | None = None,
        input_str: str | None = None,
        run_id: Any | None = None,
        **kwargs: Any,
    ) -> None:
        """Emit ``event: tool_start`` with the tool's display name + latency start."""
        name = (serialized or {}).get("name") or "tool"
        if run_id is None:
            run_id = f"anon-{time.perf_counter()}"
        self._tool_started_at[str(run_id)] = time.perf_counter()
        self._tool_name[str(run_id)] = name
        await self._queue.put(_format_sse_event("tool_start", {"tool": name}))

    async def on_tool_end(
        self,
        output: Any = None,
        run_id: Any | None = None,
        **kwargs: Any,
    ) -> None:
        """Emit ``event: tool_end`` with result length + latency + status ok."""
        await self._emit_tool_end(output, run_id, status="ok")

    async def on_tool_error(
        self,
        error: BaseException,
        run_id: Any | None = None,
        **kwargs: Any,
    ) -> None:
        """Emit ``event: tool_end`` with ``status="error"``; never aborts the stream."""
        await self._emit_tool_end(str(error), run_id, status="error")

    async def _emit_tool_end(
        self,
        output: Any,
        run_id: Any | None,
        *,
        status: str,
    ) -> None:
        run_id_str = str(run_id) if run_id is not None else None
        name = (self._tool_name.pop(run_id_str, None) if run_id_str else None) or "tool"
        started_at = (
            self._tool_started_at.pop(run_id_str, None) if run_id_str else None
        )
        latency_ms = (
            int((time.perf_counter() - started_at) * 1000) if started_at is not None else 0
        )
        result_length = _payload_length(output)
        await self._queue.put(
            _format_sse_event(
                "tool_end",
                {
                    "tool": name,
                    "result_length": result_length,
                    "latency_ms": latency_ms,
                    "status": status,
                },
            )
        )

    # ------------------------------------------------------------------
    # Async iterator surface
    # ------------------------------------------------------------------

    def __aiter__(self):
        return self

    async def __anext__(self) -> str:
        if self._errors:
            raise RuntimeError(self._errors[0])

        if self._done and self._queue.empty():
            raise StopAsyncIteration

        token = await self._queue.get()
        return token


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _payload_length(output: Any) -> int:
    """Compute a stable byte-length for a tool output, capped at 4000."""
    if isinstance(output, str):
        return min(len(output.encode("utf-8")), _TOOL_RESULT_MAX_BYTES)
    if output is None:
        return 0
    try:
        text = json.dumps(output, ensure_ascii=False)
    except Exception:
        text = str(output)
    return min(len(text.encode("utf-8")), _TOOL_RESULT_MAX_BYTES)


def _format_sse_event(event_name: str, data: Any) -> str:
    """Serialize a single SSE event in the canonical ``event: <name>\\ndata: <json>\\n\\n`` shape."""
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event_name}\ndata: {payload}\n\n"


def format_done_event() -> str:
    """Return the canonical ``event: done`` payload (last event on success)."""
    return _format_sse_event("done", None)


def format_error_event(message: str) -> str:
    """Return the canonical ``event: error`` payload (last event on failure)."""
    return _format_sse_event("error", message)


def format_sources_event(sources: list[dict[str, Any]]) -> str:
    """Return the canonical ``event: sources`` payload emitted by the route."""
    return _format_sse_event("sources", sources)
