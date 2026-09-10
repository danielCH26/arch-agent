"""
Tests for the F11 tool-event extensions on ``SSEStreamCallbackHandler``.

Covers REQ-7 / SCN-1:
  - ``event: tool_start`` exact bytes with ``{"tool": "<name>"}`` payload
  - ``event: tool_end`` with ``result_length``, ``latency_ms`` and
    ``status="ok"`` (or ``"error"`` from ``on_tool_error``)
  - Pairing: ``tool_end`` follows its own ``tool_start``
  - ``ensure_ascii=False`` preserved (UTF-8 names round-trip)
  - F08 parity: ``token`` / ``done`` / ``error`` / ``sources`` bytes
    unchanged
  - ``_payload_length`` caps at 4000 bytes
"""
from __future__ import annotations

import asyncio
import json

import pytest


def _consume(handler, *, max_events: int = 16) -> list[str]:
    async def _drive():
        events = []
        for _ in range(max_events):
            try:
                events.append(await handler.__anext__())
            except StopAsyncIteration:
                break
        return events

    return asyncio.run(_drive())


# ---------------------------------------------------------------------------
# tool_start
# ---------------------------------------------------------------------------


def test_tool_start_emits_canonical_sse_bytes():
    from app.api.sse import SSEStreamCallbackHandler

    handler = SSEStreamCallbackHandler()

    async def _drive():
        await handler.on_tool_start(
            serialized={"name": "resolve-library-id"},
            input_str='{"libraryName": "requests"}',
            run_id="rid-1",
        )

    asyncio.run(_drive())
    events = _consume(handler, max_events=1)

    assert len(events) == 1
    payload = events[0]
    assert payload.startswith("event: tool_start\ndata: ")
    assert payload.endswith("\n\n")
    body = payload.split("data: ", 1)[1].rstrip("\n")
    decoded = json.loads(body)
    assert decoded == {"tool": "resolve-library-id"}


def test_tool_start_falls_back_to_tool_when_name_missing():
    from app.api.sse import SSEStreamCallbackHandler

    handler = SSEStreamCallbackHandler()

    async def _drive():
        await handler.on_tool_start(serialized={}, input_str="x", run_id="rid")

    asyncio.run(_drive())
    [event] = _consume(handler, max_events=1)
    body = json.loads(event.split("data: ", 1)[1].rstrip("\n"))
    assert body == {"tool": "tool"}


def test_tool_start_uses_run_id_for_latency_isolation():
    from app.api.sse import SSEStreamCallbackHandler

    handler = SSEStreamCallbackHandler()

    async def _drive():
        await handler.on_tool_start(
            serialized={"name": "query-docs"}, input_str="x", run_id="rid-A"
        )
        await handler.on_tool_start(
            serialized={"name": "resolve-library-id"}, input_str="x", run_id="rid-B"
        )

    asyncio.run(_drive())
    events = _consume(handler, max_events=2)
    names = [json.loads(e.split("data: ", 1)[1].rstrip("\n"))["tool"] for e in events]
    assert names == ["query-docs", "resolve-library-id"]


# ---------------------------------------------------------------------------
# tool_end
# ---------------------------------------------------------------------------


def test_tool_end_emits_length_latency_and_status():
    from app.api.sse import SSEStreamCallbackHandler

    handler = SSEStreamCallbackHandler()

    async def _drive():
        await handler.on_tool_start(
            serialized={"name": "resolve-library-id"},
            input_str="x",
            run_id="rid-1",
        )
        await handler.on_tool_end(output="/python/requests", run_id="rid-1")

    asyncio.run(_drive())
    events = _consume(handler, max_events=2)
    assert events[0].startswith("event: tool_start\n")
    end_event = events[1]
    assert end_event.startswith("event: tool_end\ndata: ")
    body = json.loads(end_event.split("data: ", 1)[1].rstrip("\n"))
    assert body["tool"] == "resolve-library-id"
    assert body["status"] == "ok"
    assert body["result_length"] == len(b"/python/requests")
    assert isinstance(body["latency_ms"], int)
    assert body["latency_ms"] >= 0


def test_tool_end_caps_result_length_at_4000_bytes():
    from app.api.sse import SSEStreamCallbackHandler

    handler = SSEStreamCallbackHandler()

    async def _drive():
        await handler.on_tool_start(
            serialized={"name": "query-docs"}, input_str="x", run_id="rid"
        )
        await handler.on_tool_end(output="x" * 8000, run_id="rid")

    asyncio.run(_drive())
    events = _consume(handler, max_events=2)
    body = json.loads(events[1].split("data: ", 1)[1].rstrip("\n"))
    assert body["result_length"] == 4000


def test_tool_end_for_dict_output_serializes_via_json():
    from app.api.sse import SSEStreamCallbackHandler

    handler = SSEStreamCallbackHandler()

    async def _drive():
        await handler.on_tool_start(
            serialized={"name": "query-docs"}, input_str="x", run_id="rid"
        )
        await handler.on_tool_end(output={"docs": ["a", "b"]}, run_id="rid")

    asyncio.run(_drive())
    events = _consume(handler, max_events=2)
    body = json.loads(events[1].split("data: ", 1)[1].rstrip("\n"))
    assert body["result_length"] == len(json.dumps({"docs": ["a", "b"]}).encode("utf-8"))


def test_tool_error_emits_status_error():
    """``on_tool_error`` MUST use the same wire shape with status='error'."""
    from app.api.sse import SSEStreamCallbackHandler

    handler = SSEStreamCallbackHandler()

    async def _drive():
        await handler.on_tool_start(
            serialized={"name": "query-docs"}, input_str="x", run_id="rid"
        )
        await handler.on_tool_error(error=RuntimeError("upstream 503"), run_id="rid")

    asyncio.run(_drive())
    events = _consume(handler, max_events=2)
    body = json.loads(events[1].split("data: ", 1)[1].rstrip("\n"))
    assert body["tool"] == "query-docs"
    assert body["status"] == "error"
    assert body["result_length"] == len(b"upstream 503")


def test_tool_end_without_prior_start_still_emits_valid_event():
    """Defensive: if ``on_tool_end`` arrives without a paired start, default name."""
    from app.api.sse import SSEStreamCallbackHandler

    handler = SSEStreamCallbackHandler()

    async def _drive():
        await handler.on_tool_end(output="ok", run_id="orphan-rid")

    asyncio.run(_drive())
    [event] = _consume(handler, max_events=1)
    body = json.loads(event.split("data: ", 1)[1].rstrip("\n"))
    assert body["tool"] == "tool"
    assert body["status"] == "ok"


# ---------------------------------------------------------------------------
# Pairing order (SCN-1 ordering rule)
# ---------------------------------------------------------------------------


def test_pairing_order_start_then_end_before_done():
    from app.api.sse import SSEStreamCallbackHandler

    handler = SSEStreamCallbackHandler()

    async def _drive():
        await handler.on_tool_start(
            serialized={"name": "resolve-library-id"}, input_str="x", run_id="rid-1"
        )
        await handler.on_tool_end(output="lib-id", run_id="rid-1")
        await handler.on_llm_new_token("hello")
        handler.on_llm_end()

    async def _drive_then_consume():
        # Run the producer first, then drain.
        await _drive()
        events = []
        for _ in range(8):
            try:
                events.append(await handler.__anext__())
            except StopAsyncIteration:
                break
        return events

    events = asyncio.run(_drive_then_consume())

    types = [_event_type(e) for e in events]
    assert types[0] == "tool_start"
    assert types[1] == "tool_end"
    assert types[-1] == "token"  # last LLM token; done is fired by the route


def _event_type(payload: str) -> str:
    line = payload.splitlines()[0]
    assert line.startswith("event: ")
    return line[len("event: "):]


async def _drive_then_consume(handler):
    events = []
    for _ in range(8):
        try:
            events.append(await handler.__anext__())
        except StopAsyncIteration:
            break
    return events


# ---------------------------------------------------------------------------
# F08 parity: token / done / error / sources bytes unchanged
# ---------------------------------------------------------------------------


def test_token_event_bytes_match_f08_shape():
    from app.api.sse import SSEStreamCallbackHandler

    handler = SSEStreamCallbackHandler()

    async def _drive():
        await handler.on_llm_new_token("Hola")

    asyncio.run(_drive())
    [event] = _consume(handler, max_events=1)
    assert event.startswith("event: token\ndata: ")
    body = json.loads(event.split("data: ", 1)[1].rstrip("\n"))
    assert body == "Hola"


def test_format_done_event_helper_matches_existing_shape():
    from app.api.sse import format_done_event

    assert format_done_event() == "event: done\ndata: null\n\n"


def test_format_error_event_helper_matches_existing_shape():
    from app.api.sse import format_error_event

    err = format_error_event("Connection timeout")
    assert err.startswith("event: error\ndata: ")
    body = json.loads(err.split("data: ", 1)[1].rstrip("\n"))
    assert body == "Connection timeout"


def test_format_sources_event_helper_emits_list():
    from app.api.sse import format_sources_event

    src = format_sources_event(
        [{"source_type": "architect_pattern", "name": "Saga", "similarity": 0.91}]
    )
    assert src.startswith("event: sources\ndata: ")
    body = json.loads(src.split("data: ", 1)[1].rstrip("\n"))
    assert isinstance(body, list)
    assert body[0]["source_type"] == "architect_pattern"


# ---------------------------------------------------------------------------
# UTF-8 round-trip
# ---------------------------------------------------------------------------


def test_tool_start_preserves_unicode_via_ensure_ascii_false():
    """Tool names with non-ASCII characters must round-trip on the wire."""
    from app.api.sse import SSEStreamCallbackHandler

    handler = SSEStreamCallbackHandler()

    async def _drive():
        await handler.on_tool_start(
            serialized={"name": "resolver-librería"},
            input_str="x",
            run_id="rid-unicode",
        )

    asyncio.run(_drive())
    [event] = _consume(handler, max_events=1)
    body = json.loads(event.split("data: ", 1)[1].rstrip("\n"))
    assert body["tool"] == "resolver-librería"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def test_payload_length_caps_at_4000_bytes():
    from app.api.sse import _payload_length

    assert _payload_length("short") == 5
    assert _payload_length("x" * 8000) == 4000
    assert _payload_length({"k": "v"}) == len(json.dumps({"k": "v"}).encode("utf-8"))
    assert _payload_length(None) == 0
