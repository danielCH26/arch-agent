"""Smoke tests for the agent runtime module skeleton (slice F11.1).

These tests verify only that the module imports and exposes the expected
public surface and prompt constants. The real implementation lands in
slice F11.3a.
"""

from __future__ import annotations

import importlib


def test_module_imports():
    mod = importlib.import_module("app.core.agent")
    assert mod is not None


def test_prompt_constants():
    from app.core import agent

    assert isinstance(agent.ARCHITECT_PERSONA, str)
    assert "arquitectura" in agent.ARCHITECT_PERSONA.lower()
    assert isinstance(agent.LIBRARY_HINT, str)
    assert "resolve-library-id" in agent.LIBRARY_HINT
    assert "query-docs" in agent.LIBRARY_HINT
    assert agent._TOOL_RESULT_MAX_CHARS == 4000


def test_public_callables_exist():
    from app.core import agent

    assert callable(getattr(agent, "build_agent", None))
    assert callable(getattr(agent, "format_rag_context", None))
    assert callable(getattr(agent, "run_agent", None))


def test_stubs_raise_not_implemented():
    """Slice F11.1 stubs must raise ``NotImplementedError`` until F11.3a."""
    import pytest

    from app.core import agent

    with pytest.raises(NotImplementedError):
        agent.format_rag_context([])

    with pytest.raises(NotImplementedError):
        agent.build_agent(model=None, system_prompt="x")

    # run_agent is async — drive it via asyncio.run.
    import asyncio

    async def _drive():
        agen = agent.run_agent(model=None, message="x", callbacks=[])
        return await agen.__anext__()

    with pytest.raises(NotImplementedError):
        asyncio.run(_drive())
