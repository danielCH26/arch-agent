"""Tests para app.api.sse — helpers puros + ``SSEStreamCallbackHandler``."""
from __future__ import annotations
import asyncio

import time

import pytest


def _await(coro):
    """Run an awaitable (coroutine) and return the result, or None.

    LangChain's callback contract declares ``on_llm_new_token`` /
    ``on_tool_start`` / ``on_tool_end`` / ``on_tool_error`` as ``async``.
    The handler implements them as ``async def`` coroutines. In tests we
    don't need a running event loop for the duration of the assertion, so
    we drain each one synchronously with ``asyncio.run``.
    """
    if coro is None:
        return None
    if asyncio.iscoroutine(coro):
        return asyncio.run(coro)
    return coro


class TestPayloadLength:
    """_payload_length caps at _TOOL_RESULT_MAX_BYTES (4000)."""

    def test_string_payload_returns_byte_length(self):
        from app.api.sse import _payload_length

        assert _payload_length("hello") == 5

    def test_unicode_string_returns_byte_length(self):
        from app.api.sse import _payload_length

        # "ñ" is 2 bytes in UTF-8
        assert _payload_length("ñ") == 2

    def test_none_returns_zero(self):
        from app.api.sse import _payload_length

        assert _payload_length(None) == 0

    def test_dict_payload_returns_capped_byte_length(self):
        from app.api.sse import _payload_length, _TOOL_RESULT_MAX_BYTES

        big_dict = {"data": "x" * (_TOOL_RESULT_MAX_BYTES + 100)}
        result = _payload_length(big_dict)
        assert result == _TOOL_RESULT_MAX_BYTES

    def test_string_over_limit_caps_at_4000(self):
        from app.api.sse import _payload_length, _TOOL_RESULT_MAX_BYTES

        long = "a" * 5000
        assert _payload_length(long) == _TOOL_RESULT_MAX_BYTES

    def test_object_that_fails_json_uses_str(self):
        from app.api.sse import _payload_length

        class Unserializable:
            def __repr__(self):
                return "<Unserializable>"

        result = _payload_length(Unserializable())
        assert result == len(b"<Unserializable>")


class TestFormatSseEvent:
    """The _format_sse_event helper produces the canonical 'event: x\\ndata: y\\n\\n'."""

    def test_string_data(self):
        from app.api.sse import _format_sse_event

        assert _format_sse_event("token", "hello") == 'event: token\ndata: "hello"\n\n'

    def test_dict_data(self):
        from app.api.sse import _format_sse_event

        out = _format_sse_event("tool_start", {"tool": "x"})
        assert out == 'event: tool_start\ndata: {"tool": "x"}\n\n'

    def test_preserves_unicode(self):
        from app.api.sse import _format_sse_event

        out = _format_sse_event("token", "áéíóú ñ")
        assert "áéíóú" in out

    def test_emits_done_with_null(self):
        from app.api.sse import format_done_event

        assert format_done_event() == 'event: done\ndata: null\n\n'

    def test_emits_error_with_message(self):
        from app.api.sse import format_error_event

        assert format_error_event("oops") == 'event: error\ndata: "oops"\n\n'

    def test_emits_sources_list(self):
        from app.api.sse import format_sources_event

        out = format_sources_event([{"id": 1}, {"id": 2}])
        assert out.startswith("event: sources\n")
        assert '"id": 1' in out
        assert '"id": 2' in out


class TestSSEStreamCallbackHandler:
    """LangChain callback that produces SSE events."""

    def test_initial_state_has_empty_queue(self):
        from app.api.sse import SSEStreamCallbackHandler

        h = SSEStreamCallbackHandler()
        assert h._queue.empty()
        assert h._errors == []
        assert h._done is False

    def test_on_llm_new_token_enqueues_sse_event(self):
        from app.api.sse import SSEStreamCallbackHandler

        h = SSEStreamCallbackHandler()
        _await(h.on_llm_new_token(token="hello"))

        item = h._queue.get_nowait()
        assert item == 'event: token\ndata: "hello"\n\n'

    def test_on_llm_new_token_skips_empty(self):
        from app.api.sse import SSEStreamCallbackHandler

        h = SSEStreamCallbackHandler()
        _await(h.on_llm_new_token(token=""))
        assert h._queue.empty()

    def test_on_llm_end_marks_done(self):
        from app.api.sse import SSEStreamCallbackHandler

        h = SSEStreamCallbackHandler()
        h.on_llm_end()
        assert h._done is True

    def test_on_llm_error_records_error_and_marks_done(self):
        from app.api.sse import SSEStreamCallbackHandler

        h = SSEStreamCallbackHandler()
        h.on_llm_error(error=ValueError("boom"))
        assert h._errors == ["boom"]
        assert h._done is True

    def test_on_tool_start_records_name_and_emits_event(self):
        from app.api.sse import SSEStreamCallbackHandler

        h = SSEStreamCallbackHandler()
        serialized = {"name": "context7_search"}
        _await(h.on_tool_start(serialized=serialized, run_id="run-123"))

        item = h._queue.get_nowait()
        assert item == 'event: tool_start\ndata: {"tool": "context7_search"}\n\n'
        assert h._tool_name["run-123"] == "context7_search"
        assert "run-123" in h._tool_started_at

    def test_on_tool_start_uses_fallback_name_when_serialized_missing(self):
        from app.api.sse import SSEStreamCallbackHandler

        h = SSEStreamCallbackHandler()
        _await(h.on_tool_start(serialized=None, run_id="run-1"))

        item = h._queue.get_nowait()
        assert item == 'event: tool_start\ndata: {"tool": "tool"}\n\n'

    def test_on_tool_end_emits_ok_with_latency_and_length(self):
        from app.api.sse import SSEStreamCallbackHandler

        h = SSEStreamCallbackHandler()
        serialized = {"name": "search"}
        _await(h.on_tool_start(serialized=serialized, run_id="run-1"))
        h._queue.get_nowait()  # drain tool_start

        time.sleep(0.001)  # ensure non-zero latency
        _await(h.on_tool_end(output="result text here", run_id="run-1"))

        item = h._queue.get_nowait()
        assert '"tool": "search"' in item
        assert '"status": "ok"' in item
        assert '"result_length": 16' in item
        assert '"latency_ms"' in item

    def test_on_tool_error_emits_status_error(self):
        from app.api.sse import SSEStreamCallbackHandler

        h = SSEStreamCallbackHandler()
        serialized = {"name": "flaky"}
        _await(h.on_tool_start(serialized=serialized, run_id="run-1"))
        h._queue.get_nowait()

        _await(h.on_tool_error(error=RuntimeError("kaboom"), run_id="run-1"))

        item = h._queue.get_nowait()
        assert '"tool": "flaky"' in item
        assert '"status": "error"' in item

    def test_on_tool_end_without_prior_start_uses_defaults(self):
        """If tool_end arrives without tool_start (e.g. error during start),
        the latency should be 0 and the name should fall back to ``tool``."""
        from app.api.sse import SSEStreamCallbackHandler

        h = SSEStreamCallbackHandler()
        _await(h.on_tool_end(output="some output", run_id="never-started"))

        item = h._queue.get_nowait()
        assert '"tool": "tool"' in item
        assert '"status": "ok"' in item
        assert '"latency_ms": 0' in item

    def test_tool_end_caps_result_length_at_4000_bytes(self):
        from app.api.sse import SSEStreamCallbackHandler
        from app.api.sse import _TOOL_RESULT_MAX_BYTES

        h = SSEStreamCallbackHandler()
        _await(h.on_tool_start(serialized={"name": "x"}, run_id="r"))
        h._queue.get_nowait()

        huge = "y" * (_TOOL_RESULT_MAX_BYTES + 500)
        _await(h.on_tool_end(output=huge, run_id="r"))

        item = h._queue.get_nowait()
        # result_length is the byte count, capped at TOOL_RESULT_MAX_BYTES
        assert f'"result_length": {_TOOL_RESULT_MAX_BYTES}' in item

    def test_tool_end_for_dict_output_records_byte_length(self):
        """Dict outputs are not echoed in the SSE; only the byte length is logged.
        The byte length is computed via json.dumps(ensure_ascii=False) and capped
        at ``_TOOL_RESULT_MAX_BYTES`` (4000)."""
        from app.api.sse import SSEStreamCallbackHandler

        h = SSEStreamCallbackHandler()
        _await(h.on_tool_start(serialized={"name": "x"}, run_id="r"))
        h._queue.get_nowait()

        # Dict serializes to ~24 bytes via json.dumps(ensure_ascii=False)
        _await(h.on_tool_end(output={"result": "structured"}, run_id="r"))

        item = h._queue.get_nowait()
        assert '"tool": "x"' in item
        assert '"result_length": 24' in item
        assert '"status": "ok"' in item

    def test_tool_start_preserves_unicode_via_ensure_ascii_false(self):
        from app.api.sse import SSEStreamCallbackHandler

        h = SSEStreamCallbackHandler()
        _await(h.on_tool_start(
            serialized={"name": "Búsqueda con ñ"},
            run_id="r",
        ))

        item = h._queue.get_nowait()
        assert "Búsqueda con ñ" in item

    def test_anext_returns_token_events(self):
        from app.api.sse import SSEStreamCallbackHandler

        h = SSEStreamCallbackHandler()
        _await(h.on_llm_new_token(token="hello"))

        item = asyncio.run(h.__anext__())
        assert item == 'event: token\ndata: "hello"\n\n'

    def test_anext_raises_runtime_error_when_errors_recorded(self):
        from app.api.sse import SSEStreamCallbackHandler

        h = SSEStreamCallbackHandler()
        h.on_llm_error(error=ValueError("something failed"))

        with pytest.raises(RuntimeError, match="something failed"):
            asyncio.run(h.__anext__())

    def test_anext_stops_after_done_and_empty_queue(self):
        from app.api.sse import SSEStreamCallbackHandler

        h = SSEStreamCallbackHandler()
        h.on_llm_end()  # marks done, queue is empty

        with pytest.raises(StopAsyncIteration):
            asyncio.run(h.__anext__())

    def test_anext_drains_multiple_events_before_stopping(self):
        from app.api.sse import SSEStreamCallbackHandler

        h = SSEStreamCallbackHandler()
        _await(h.on_llm_new_token(token="one"))
        _await(h.on_llm_new_token(token="two"))
        h.on_llm_end()

        # Two events should come out before StopAsyncIteration
        first = asyncio.run(h.__anext__())
        second = asyncio.run(h.__anext__())
        assert "one" in first
        assert "two" in second

        with pytest.raises(StopAsyncIteration):
            asyncio.run(h.__anext__())

    def test_aiter_returns_self(self):
        from app.api.sse import SSEStreamCallbackHandler

        h = SSEStreamCallbackHandler()
        assert h.__aiter__() is h