"""Authorization middleware for FastMCP.

This module provides middleware-based authorization using callable auth checks.
AuthMiddleware applies auth checks globally to all components on the server.

Example:
    ```python
    from fastmcp import FastMCP
    from fastmcp.server.auth import require_scopes, restrict_tag
    from fastmcp.server.middleware import AuthMiddleware

    # Require specific scope for all components
    mcp = FastMCP(middleware=[
        AuthMiddleware(auth=require_scopes("api"))
    ])

    # Tag-based: components tagged "admin" require "admin" scope
    mcp = FastMCP(middleware=[
        AuthMiddleware(auth=restrict_tag("admin", scopes=["admin"]))
    ])
    ```
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

import mcp.types as mt

from fastmcp.exceptions import AuthorizationError
from fastmcp.prompts.base import Prompt, PromptResult
from fastmcp.resources.base import Resource, ResourceResult
from fastmcp.resources.template import ResourceTemplate
from fastmcp.server.auth.authorization import (
    AuthCheck,
    AuthContext,
    run_auth_checks,
)
from fastmcp.server.dependencies import get_access_token
from fastmcp.server.middleware.middleware import (
    CallNext,
    Middleware,
    MiddlewareContext,
)
from fastmcp.tools.base import Tool, ToolResult

logger = logging.getLogger(__name__)


class AuthMiddleware(Middleware):
    """Global authorization middleware using callable checks.

    This middleware applies auth checks to all components (tools, resources,
    prompts) on the server. It uses the same callable API as component-level
    auth checks.

    The middleware:
    - Filters tools/resources/prompts from list responses based on auth checks
    - Checks auth before tool execution, resource read, and prompt render
    - Skips all auth checks for STDIO transport (no OAuth concept)

    Args:
        auth: A single auth check function or list of check functions.
            All checks must pass for authorization to succeed (AND logic).

    Example:
        ```python
        from fastmcp import FastMCP
        from fastmcp.server.auth import require_scopes

        # Require specific scope for all components
        mcp = FastMCP(middleware=[AuthMiddleware(auth=require_scopes("api"))])

        # Multiple scopes (AND logic)
        mcp = FastMCP(middleware=[
            AuthMiddleware(auth=require_scopes("read", "api"))
        ])
        ```
    """

    def __init__(self, auth: AuthCheck | list[AuthCheck]) -> None:
        self.auth = auth

    async def on_list_tools(
        self,
        context: MiddlewareContext[mt.ListToolsRequest],
        call_next: CallNext[mt.ListToolsRequest, Sequence[Tool]],
    ) -> Sequence[Tool]:
        """Filter tools/list response based on auth checks."""
        pass

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        """Check auth before tool execution."""
        pass

    async def on_list_resources(
        self,
        context: MiddlewareContext[mt.ListResourcesRequest],
        call_next: CallNext[mt.ListResourcesRequest, Sequence[Resource]],
    ) -> Sequence[Resource]:
        """Filter resources/list response based on auth checks."""
        pass

    async def on_read_resource(
        self,
        context: MiddlewareContext[mt.ReadResourceRequestParams],
        call_next: CallNext[mt.ReadResourceRequestParams, ResourceResult],
    ) -> ResourceResult:
        """Check auth before resource read."""
        pass

    async def on_list_resource_templates(
        self,
        context: MiddlewareContext[mt.ListResourceTemplatesRequest],
        call_next: CallNext[
            mt.ListResourceTemplatesRequest, Sequence[ResourceTemplate]
        ],
    ) -> Sequence[ResourceTemplate]:
        """Filter resource templates/list response based on auth checks."""
        pass

    async def on_list_prompts(
        self,
        context: MiddlewareContext[mt.ListPromptsRequest],
        call_next: CallNext[mt.ListPromptsRequest, Sequence[Prompt]],
    ) -> Sequence[Prompt]:
        """Filter prompts/list response based on auth checks."""
        pass

    async def on_get_prompt(
        self,
        context: MiddlewareContext[mt.GetPromptRequestParams],
        call_next: CallNext[mt.GetPromptRequestParams, PromptResult],
    ) -> PromptResult:
        """Check auth before prompt render."""
        pass
