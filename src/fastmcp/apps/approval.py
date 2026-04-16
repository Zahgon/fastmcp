"""Approval — a Provider that adds human-in-the-loop approval to any server.

The LLM presents a summary of what it's about to do, and the user
approves or rejects via buttons. The result is sent back into the
conversation as a message, prompting the LLM's next turn.

Requires ``fastmcp[apps]`` (prefab-ui).

Usage::

    from fastmcp import FastMCP
    from fastmcp.apps.approval import Approval

    mcp = FastMCP("My Server")
    mcp.add_provider(Approval())
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
        Row,
        Text,
    )
    from prefab_ui.components.control_flow import If
    from prefab_ui.rx import STATE
except ImportError as _exc:
    raise ImportError(
        "Approval requires prefab-ui. Install with: pip install 'fastmcp[apps]'"
    ) from _exc


from fastmcp.apps.app import FastMCPApp


class Approval(FastMCPApp):
    """A Provider that adds human-in-the-loop approval to a server.

    The LLM calls the ``request_approval`` tool with a summary and
    optional details. The user sees an approval card with Approve and
    Reject buttons. Clicking either sends a message back into the
    conversation (via ``SendMessage``), triggering the LLM's next turn.

    The message appears as if the user sent it, so the LLM sees
    something like ``'"Deploy v3.2 to production" is APPROVED'``.

    Example::

        from fastmcp import FastMCP
        from fastmcp.apps.approval import Approval

        mcp = FastMCP("My Server")
        mcp.add_provider(Approval())

    Customized::

        Approval(
            title="Deploy Gate",
            approve_text="Ship it",
            approve_variant="default",
            reject_text="Abort",
            reject_variant="destructive",
        )
    """

    def __init__(
        self,
        name: str = "Approval",
        *,
        title: str = "Approval Required",
        approve_text: str = "Approve",
        reject_text: str = "Reject",
        approve_variant: Literal[
            "default", "destructive", "success", "info"
        ] = "default",
        reject_variant: Literal[
            "default", "outline", "destructive", "success", "info"
        ] = "outline",
    ) -> None:
        super().__init__(name)
        self._title = title
        self._approve_text = approve_text
        self._reject_text = reject_text
        self._approve_variant = approve_variant
        self._reject_variant = reject_variant
        self._register_tools()

    def __repr__(self) -> str:
        return f"Approval({self.name!r})"

    def _register_tools(self) -> None:
        pass
