"""MCP protocol handler setup and wire-format handlers for FastMCP Server."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import TYPE_CHECKING, Any, TypeVar, cast

import mcp.types
from mcp.shared.exceptions import McpError
from mcp.types import ContentBlock
from pydantic import AnyUrl

from fastmcp.exceptions import DisabledError, NotFoundError
from fastmcp.server.tasks.config import TaskMeta
from fastmcp.utilities.logging import get_logger
from fastmcp.utilities.pagination import paginate_sequence
from fastmcp.utilities.versions import VersionSpec, dedupe_with_versions

if TYPE_CHECKING:
    from fastmcp.server.server import FastMCP

logger = get_logger(__name__)

PaginateT = TypeVar("PaginateT")


def _apply_pagination(
    items: Sequence[PaginateT],
    cursor: str | None,
    page_size: int | None,
) -> tuple[list[PaginateT], str | None]:
    """Apply pagination to items, raising McpError for invalid cursors.

    If page_size is None, returns all items without pagination.
    """
    pass


class MCPOperationsMixin:
    """Mixin providing MCP protocol handler setup and wire-format handlers.

    Note: Methods registered with SDK decorators (e.g., _list_tools_mcp, _call_tool_mcp)
    cannot use `self: FastMCP` type hints because the SDK's `get_type_hints()` fails
    to resolve FastMCP at runtime (it's only available under TYPE_CHECKING). When
    type hints fail to resolve, the SDK falls back to calling handlers with no arguments.
    These methods use untyped `self` to avoid this issue.
    """

    def _setup_handlers(self: FastMCP) -> None:
        """Set up core MCP protocol handlers.

        List handlers use SDK decorators that pass the request object to our handler
        (needed for pagination cursor). The SDK also populates caches like _tool_cache.

        Exception: list_resource_templates SDK decorator doesn't pass the request,
        so we register that handler directly.

        The call_tool decorator is from the SDK (supports CreateTaskResult + validate_input).
        The read_resource and get_prompt decorators are from LowLevelServer to add
        CreateTaskResult support until the SDK provides it natively.
        """
        pass

    def _wrap_list_handler(
        self: FastMCP, handler: Callable[..., Awaitable[Any]]
    ) -> Callable[..., Awaitable[mcp.types.ServerResult]]:
        """Wrap a list handler to pass the request and return ServerResult."""
        pass

    async def _list_tools_mcp(
        self, request: mcp.types.ListToolsRequest
    ) -> mcp.types.ListToolsResult:
        """
        List all available tools, in the format expected by the low-level MCP
        server. Supports pagination when list_page_size is configured.
        """
        pass

    async def _list_resources_mcp(
        self, request: mcp.types.ListResourcesRequest
    ) -> mcp.types.ListResourcesResult:
        """
        List all available resources, in the format expected by the low-level MCP
        server. Supports pagination when list_page_size is configured.
        """
        pass

    async def _list_resource_templates_mcp(
        self, request: mcp.types.ListResourceTemplatesRequest
    ) -> mcp.types.ListResourceTemplatesResult:
        """
        List all available resource templates, in the format expected by the low-level MCP
        server. Supports pagination when list_page_size is configured.
        """
        pass

    async def _list_prompts_mcp(
        self, request: mcp.types.ListPromptsRequest
    ) -> mcp.types.ListPromptsResult:
        """
        List all available prompts, in the format expected by the low-level MCP
        server. Supports pagination when list_page_size is configured.
        """
        pass

    async def _call_tool_mcp(
        self, key: str, arguments: dict[str, Any]
    ) -> (
        list[ContentBlock]
        | tuple[list[ContentBlock], dict[str, Any]]
        | mcp.types.CallToolResult
        | mcp.types.CreateTaskResult
    ):
        """
        Handle MCP 'callTool' requests.

        Extracts task metadata from MCP request context and passes it explicitly
        to call_tool(). The tool's _run() method handles the backgrounding decision,
        ensuring middleware runs before Docket.

        Args:
            key: The name of the tool to call
            arguments: Arguments to pass to the tool

        Returns:
            Tool result or CreateTaskResult for background execution
        """
        pass

    async def _read_resource_mcp(
        self, uri: AnyUrl | str
    ) -> mcp.types.ReadResourceResult | mcp.types.CreateTaskResult:
        """Handle MCP 'readResource' requests.

        Extracts task metadata from MCP request context and passes it explicitly
        to read_resource(). The resource's _read() method handles the backgrounding
        decision, ensuring middleware runs before Docket.

        Args:
            uri: The resource URI

        Returns:
            ReadResourceResult or CreateTaskResult for background execution
        """
        pass

    async def _get_prompt_mcp(
        self, name: str, arguments: dict[str, Any] | None
    ) -> mcp.types.GetPromptResult | mcp.types.CreateTaskResult:
        """Handle MCP 'getPrompt' requests.

        Extracts task metadata from MCP request context and passes it explicitly
        to render_prompt(). The prompt's _render() method handles the backgrounding
        decision, ensuring middleware runs before Docket.

        Args:
            name: The prompt name
            arguments: Prompt arguments

        Returns:
            GetPromptResult or CreateTaskResult for background execution
        """
        pass

    async def _set_logging_level_mcp(self, level: mcp.types.LoggingLevel) -> None:
        """Handle MCP 'logging/setLevel' requests.

        Stores the requested minimum log level on the session so that
        subsequent log messages below this level are suppressed.
        """
        pass
