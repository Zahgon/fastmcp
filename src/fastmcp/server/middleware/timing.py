"""Timing middleware for measuring and logging request performance."""

import logging
import time
from typing import Any

from .middleware import CallNext, Middleware, MiddlewareContext


class TimingMiddleware(Middleware):
    """Middleware that logs the execution time of requests.

    Only measures and logs timing for request messages (not notifications).
    Provides insights into performance characteristics of your MCP server.

    Example:
        ```python
        from fastmcp.server.middleware.timing import TimingMiddleware

        mcp = FastMCP("MyServer")
        mcp.add_middleware(TimingMiddleware())

        # Now all requests will be timed and logged
        ```
    """

    def __init__(
        self, logger: logging.Logger | None = None, log_level: int = logging.INFO
    ):
        """Initialize timing middleware.

        Args:
            logger: Logger instance to use. If None, creates a logger named 'fastmcp.timing'
            log_level: Log level for timing messages (default: INFO)
        """
        self.logger = logger or logging.getLogger("fastmcp.timing")
        self.log_level = log_level

    async def on_request(self, context: MiddlewareContext, call_next: CallNext) -> Any:
        """Time request execution and log the results."""
        pass


class DetailedTimingMiddleware(Middleware):
    """Enhanced timing middleware with per-operation breakdowns.

    Provides detailed timing information for different types of MCP operations,
    allowing you to identify performance bottlenecks in specific operations.

    Example:
        ```python
        from fastmcp.server.middleware.timing import DetailedTimingMiddleware
        import logging

        # Configure logging to see the output
        logging.basicConfig(level=logging.INFO)

        mcp = FastMCP("MyServer")
        mcp.add_middleware(DetailedTimingMiddleware())
        ```
    """

    def __init__(
        self, logger: logging.Logger | None = None, log_level: int = logging.INFO
    ):
        """Initialize detailed timing middleware.

        Args:
            logger: Logger instance to use. If None, creates a logger named 'fastmcp.timing.detailed'
            log_level: Log level for timing messages (default: INFO)
        """
        self.logger = logger or logging.getLogger("fastmcp.timing.detailed")
        self.log_level = log_level

    async def _time_operation(
        self, context: MiddlewareContext, call_next: CallNext, operation_name: str
    ) -> Any:
        """Helper method to time any operation."""
        pass

    async def on_call_tool(
        self, context: MiddlewareContext, call_next: CallNext
    ) -> Any:
        """Time tool execution."""
        pass

    async def on_read_resource(
        self, context: MiddlewareContext, call_next: CallNext
    ) -> Any:
        """Time resource reading."""
        pass

    async def on_get_prompt(
        self, context: MiddlewareContext, call_next: CallNext
    ) -> Any:
        """Time prompt retrieval."""
        pass

    async def on_list_tools(
        self, context: MiddlewareContext, call_next: CallNext
    ) -> Any:
        """Time tool listing."""
        pass

    async def on_list_resources(
        self, context: MiddlewareContext, call_next: CallNext
    ) -> Any:
        """Time resource listing."""
        pass

    async def on_list_resource_templates(
        self, context: MiddlewareContext, call_next: CallNext
    ) -> Any:
        """Time resource template listing."""
        pass

    async def on_list_prompts(
        self, context: MiddlewareContext, call_next: CallNext
    ) -> Any:
        """Time prompt listing."""
        pass
