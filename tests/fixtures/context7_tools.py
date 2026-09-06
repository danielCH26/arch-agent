"""
Recorded Context7 tool-list fixture.

Offline copy of the public tool surface served by ``https://mcp.context7.com/mcp``
at design time. The names here are pinned by SCN-8; if Context7 ever renames
a tool the recorded fixture will detect it before the live integration does.

This file has no production runtime impact; it is consumed only by
``tests/core/test_context7_mcp.py`` for offline assertions.
"""

from __future__ import annotations

from typing import Any


# Pinned tool names — exactly the two Context7 serves today (SCN-8).
EXPECTED_TOOL_NAMES: tuple[str, ...] = (
    "resolve-library-id",
    "query-docs",
)


def _make_recorded_tool(name: str, description: str) -> Any:
    """Build a minimal stand-in that satisfies ``BaseTool.name`` access only.

    We don't subclass ``BaseTool`` here because tests inspect ``tool.name``;
    a plain object is enough.
    """

    class _RecordedTool:
        def __init__(self, n: str, d: str) -> None:
            self.name = n
            self.description = d

        def __repr__(self) -> str:
            return f"<RecordedTool name={self.name!r}>"

    return _RecordedTool(name, description)


def get_recorded_context7_tools() -> list[Any]:
    """Return the offline tool surface for Context7 (SCN-8 fixture)."""
    return [
        _make_recorded_tool(
            "resolve-library-id",
            "Resolves a library name (e.g. ``requests``) to a Context7 "
            "library id (e.g. ``/python/requests``).",
        ),
        _make_recorded_tool(
            "query-docs",
            "Fetches up-to-date documentation snippets for a Context7 "
            "library id plus a free-form query string.",
        ),
    ]
