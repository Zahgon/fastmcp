"""Choice — a Provider that lets the user pick from a set of options.

The LLM presents options, the user clicks one, and the selection
flows back into the conversation as a message.

Requires ``fastmcp[apps]`` (prefab-ui).

Usage::

    from fastmcp import FastMCP
    from fastmcp.apps.choice import Choice

    mcp = FastMCP("My Server")
    mcp.add_provider(Choice())
"""

from __future__ import annotations

from typing import Literal

try:
    from prefab_ui.actions import SetState
    from prefab_ui.actions.mcp import SendMessage
    from prefab_ui.app import PrefabApp
    from prefab_ui.components import (
        H3,
        Button,
        Card,
        CardContent,
        CardFooter,
        CardHeader,
        Column,
        Muted,
        Text,
    )
    from prefab_ui.components.control_flow import If
    from prefab_ui.rx import STATE
except ImportError as _exc:
    raise ImportError(
        "Choice requires prefab-ui. Install with: pip install 'fastmcp[apps]'"
    ) from _exc

from fastmcp.apps.app import FastMCPApp


class Choice(FastMCPApp):
    """A Provider that lets the user choose from a set of options.

    The LLM calls ``choose`` with a prompt and a list of options.
    The user sees a card with one button per option. Clicking a button
    sends the selection back into the conversation via ``SendMessage``,
    triggering the LLM's next turn.

    Example::

        from fastmcp import FastMCP
        from fastmcp.apps.choice import Choice

        mcp = FastMCP("My Server")
        mcp.add_provider(Choice())
    """

    def __init__(
        self,
        name: str = "Choice",
        *,
        title: str = "Choose an Option",
        variant: Literal[
            "default", "outline", "destructive", "success", "info"
        ] = "outline",
    ) -> None:
        super().__init__(name)
        self._title = title
        self._variant = variant
        self._register_tools()

    def __repr__(self) -> str:
        return f"Choice({self.name!r})"

    def _register_tools(self) -> None:
        pass
