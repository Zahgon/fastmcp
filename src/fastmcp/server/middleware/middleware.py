from __future__ import annotations

import logging
from collections.abc import Awaitable, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from functools import partial
from typing import (
    TYPE_CHECKING,
    Any,
    Generic,
    Literal,
    Protocol,
    runtime_checkable,
)

import mcp.types as mt
from typing_extensions import TypeVar

from fastmcp.prompts.base import Prompt, PromptResult
from fastmcp.resources.base import Resource, ResourceResult
from fastmcp.resources.template import ResourceTemplate
from fastmcp.tools.base import Tool, ToolResult

if TYPE_CHECKING:
    from fastmcp.server.context import Context

__all__ = [
    "CallNext",
    "Middleware",
    "MiddlewareContext",
]

logger = logging.getLogger(__name__)


T = TypeVar("T", default=Any)
R = TypeVar("R", covariant=True, default=Any)


@runtime_checkable
class CallNext(Protocol[T, R]):
    def __call__(self, context: MiddlewareContext[T]) -> Awaitable[R]: ...


@dataclass(kw_only=True, frozen=True)
class MiddlewareContext(Generic[T]):
    """
    Unified context for all middleware operations.
    """

    message: T

    fastmcp_context: Context | None = None

    # Common metadata
    source: Literal["client", "server"] = "client"
    type: Literal["request", "notification"] = "request"
    method: str | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def copy(self, **kwargs: Any) -> MiddlewareContext[T]:
        return replace(self, **kwargs)


def make_middleware_wrapper(
    middleware: Middleware, call_next: CallNext[T, R]
) -> CallNext[T, R]:
    """Create a wrapper that applies a single middleware to a context. The
    closure bakes in the middleware and call_next function, so it can be
    passed to other functions that expect a call_next function."""
    pass


class Middleware:
    """Base class for FastMCP middleware with dispatching hooks."""

    async def __call__(
        self,
        context: MiddlewareContext[T],
        call_next: CallNext[T, Any],
    ) -> Any:
        """Main entry point that orchestrates the pipeline."""
        handler_chain = await self._dispatch_handler(
            context,
            call_next=call_next,
        )
        return await handler_chain(context)

    async def _dispatch_handler(
        self, context: MiddlewareContext[Any], call_next: CallNext[Any, Any]
    ) -> CallNext[Any, Any]:
        """Builds a chain of handlers for a given message."""
        pass

    async def on_message(
        self,
        context: MiddlewareContext[Any],
        call_next: CallNext[Any, Any],
    ) -> Any:
        pass

    async def on_request(
        self,
        context: MiddlewareContext[mt.Request[Any, Any]],
        call_next: CallNext[mt.Request[Any, Any], Any],
    ) -> Any:
        pass

    async def on_notification(
        self,
        context: MiddlewareContext[mt.Notification[Any, Any]],
        call_next: CallNext[mt.Notification[Any, Any], Any],
    ) -> Any:
        pass

    async def on_initialize(
        self,
        context: MiddlewareContext[mt.InitializeRequest],
        call_next: CallNext[mt.InitializeRequest, mt.InitializeResult | None],
    ) -> mt.InitializeResult | None:
        pass

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        pass

    async def on_read_resource(
        self,
        context: MiddlewareContext[mt.ReadResourceRequestParams],
        call_next: CallNext[mt.ReadResourceRequestParams, ResourceResult],
    ) -> ResourceResult:
        pass

    async def on_get_prompt(
        self,
        context: MiddlewareContext[mt.GetPromptRequestParams],
        call_next: CallNext[mt.GetPromptRequestParams, PromptResult],
    ) -> PromptResult:
        pass

    async def on_list_tools(
        self,
        context: MiddlewareContext[mt.ListToolsRequest],
        call_next: CallNext[mt.ListToolsRequest, Sequence[Tool]],
    ) -> Sequence[Tool]:
        pass

    async def on_list_resources(
        self,
        context: MiddlewareContext[mt.ListResourcesRequest],
        call_next: CallNext[mt.ListResourcesRequest, Sequence[Resource]],
    ) -> Sequence[Resource]:
        pass

    async def on_list_resource_templates(
        self,
        context: MiddlewareContext[mt.ListResourceTemplatesRequest],
        call_next: CallNext[
            mt.ListResourceTemplatesRequest, Sequence[ResourceTemplate]
        ],
    ) -> Sequence[ResourceTemplate]:
        pass

    async def on_list_prompts(
        self,
        context: MiddlewareContext[mt.ListPromptsRequest],
        call_next: CallNext[mt.ListPromptsRequest, Sequence[Prompt]],
    ) -> Sequence[Prompt]:
        pass
