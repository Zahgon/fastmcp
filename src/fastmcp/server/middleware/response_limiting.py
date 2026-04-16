"""Response limiting middleware for controlling tool response sizes."""

from __future__ import annotations

import logging
from typing import Any

import mcp.types as mt
import pydantic_core
from mcp.types import TextContent

from fastmcp.tools.base import ToolResult

from .middleware import CallNext, Middleware, MiddlewareContext

__all__ = ["ResponseLimitingMiddleware"]

logger = logging.getLogger(__name__)


class ResponseLimitingMiddleware(Middleware):
    """Middleware that limits the response size of tool calls.

    Intercepts tool call responses and enforces size limits. If a response
    exceeds the limit, it extracts text content, truncates it, and returns
    a single TextContent block.

    Example:
        ```python
        from fastmcp import FastMCP
        from fastmcp.server.middleware.response_limiting import (
            ResponseLimitingMiddleware,
        )

        mcp = FastMCP("MyServer")

        # Limit all tool responses to 500KB
        mcp.add_middleware(ResponseLimitingMiddleware(max_size=500_000))

        # Limit only specific tools
        mcp.add_middleware(
            ResponseLimitingMiddleware(
                max_size=100_000,
                tools=["search", "fetch_data"],
            )
        )
        ```
    """

    def __init__(
        self,
        *,
        max_size: int = 1_000_000,
        truncation_suffix: str = "\n\n[Response truncated due to size limit]",
        tools: list[str] | None = None,
    ) -> None:
        """Initialize response limiting middleware.

        Args:
            max_size: Maximum response size in bytes. Defaults to 1MB (1,000,000).
            truncation_suffix: Suffix to append when truncating responses.
                Defaults to "\\n\\n[Response truncated due to size limit]".
            tools: List of tool names to apply limiting to. If None, applies to all.
        """
        if max_size <= 0:
            raise ValueError(f"max_size must be positive, got {max_size}")
        self.max_size = max_size
        self.truncation_suffix = truncation_suffix
        self.tools = set(tools) if tools is not None else None

    def _truncate_to_result(
        self,
        text: str,
        meta: dict[str, Any] | None = None,
    ) -> ToolResult:
        """Truncate text to fit within max_size and wrap in ToolResult."""
        pass

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        """Intercept tool calls and limit response size."""
        pass
