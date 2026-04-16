"""Middleware that dereferences $ref in JSON schemas before sending to clients."""

from collections.abc import Sequence
from typing import Any

import mcp.types as mt
from typing_extensions import override

from fastmcp.resources.template import ResourceTemplate
from fastmcp.server.middleware.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools.base import Tool
from fastmcp.utilities.json_schema import dereference_refs


class DereferenceRefsMiddleware(Middleware):
    """Dereferences $ref in component schemas before sending to clients.

    Some MCP clients (e.g., VS Code Copilot) don't handle JSON Schema $ref
    properly. This middleware inlines all $ref definitions so schemas are
    self-contained. Enabled by default via ``FastMCP(dereference_schemas=True)``.
    """

    @override
    async def on_list_tools(
        self,
        context: MiddlewareContext[mt.ListToolsRequest],
        call_next: CallNext[mt.ListToolsRequest, Sequence[Tool]],
    ) -> Sequence[Tool]:
        pass

    @override
    async def on_list_resource_templates(
        self,
        context: MiddlewareContext[mt.ListResourceTemplatesRequest],
        call_next: CallNext[
            mt.ListResourceTemplatesRequest, Sequence[ResourceTemplate]
        ],
    ) -> Sequence[ResourceTemplate]:
        pass


def _dereference_tool(tool: Tool) -> Tool:
    """Return a copy of the tool with dereferenced schemas."""
    pass


def _dereference_resource_template(template: ResourceTemplate) -> ResourceTemplate:
    """Return a copy of the template with dereferenced schemas."""
    pass


def _has_ref(schema: dict[str, Any]) -> bool:
    """Check if a schema contains any $ref."""
    pass
