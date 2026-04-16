"""Error handling middleware for consistent error responses and tracking."""

import asyncio
import logging
import traceback
from collections.abc import Callable
from typing import Any

import anyio
from mcp import McpError
from mcp.types import ErrorData

from fastmcp.exceptions import NotFoundError

from .middleware import CallNext, Middleware, MiddlewareContext


class ErrorHandlingMiddleware(Middleware):
    """Middleware that provides consistent error handling and logging.

    Catches exceptions, logs them appropriately, and converts them to
    proper MCP error responses. Also tracks error patterns for monitoring.

    Example:
        ```python
        from fastmcp.server.middleware.error_handling import ErrorHandlingMiddleware
        import logging

        # Configure logging to see error details
        logging.basicConfig(level=logging.ERROR)

        mcp = FastMCP("MyServer")
        mcp.add_middleware(ErrorHandlingMiddleware())
        ```
    """

    def __init__(
        self,
        logger: logging.Logger | None = None,
        include_traceback: bool = False,
        error_callback: Callable[[Exception, MiddlewareContext], None] | None = None,
        transform_errors: bool = True,
    ):
        """Initialize error handling middleware.

        Args:
            logger: Logger instance for error logging. If None, uses 'fastmcp.errors'
            include_traceback: Whether to include full traceback in error logs
            error_callback: Optional callback function called for each error
            transform_errors: Whether to transform non-MCP errors to McpError
        """
        self.logger = logger or logging.getLogger("fastmcp.errors")
        self.include_traceback = include_traceback
        self.error_callback = error_callback
        self.transform_errors = transform_errors
        self.error_counts = {}

    def _log_error(self, error: Exception, context: MiddlewareContext) -> None:
        """Log error with appropriate detail level."""
        pass

    def _transform_error(
        self, error: Exception, context: MiddlewareContext
    ) -> Exception:
        """Transform non-MCP errors to proper MCP errors."""
        pass

    async def on_message(self, context: MiddlewareContext, call_next: CallNext) -> Any:
        """Handle errors for all messages."""
        pass

    def get_error_stats(self) -> dict[str, int]:
        """Get error statistics for monitoring."""
        pass


class RetryMiddleware(Middleware):
    """Middleware that implements automatic retry logic for failed requests.

    Retries requests that fail with transient errors, using exponential
    backoff to avoid overwhelming the server or external dependencies.

    Example:
        ```python
        from fastmcp.server.middleware.error_handling import RetryMiddleware

        # Retry up to 3 times with exponential backoff
        retry_middleware = RetryMiddleware(
            max_retries=3,
            retry_exceptions=(ConnectionError, TimeoutError)
        )

        mcp = FastMCP("MyServer")
        mcp.add_middleware(retry_middleware)
        ```
    """

    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        backoff_multiplier: float = 2.0,
        retry_exceptions: tuple[type[Exception], ...] = (ConnectionError, TimeoutError),
        logger: logging.Logger | None = None,
    ):
        """Initialize retry middleware.

        Args:
            max_retries: Maximum number of retry attempts
            base_delay: Initial delay between retries in seconds
            max_delay: Maximum delay between retries in seconds
            backoff_multiplier: Multiplier for exponential backoff
            retry_exceptions: Tuple of exception types that should trigger retries
            logger: Logger for retry attempts
        """
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.backoff_multiplier = backoff_multiplier
        self.retry_exceptions = retry_exceptions
        self.logger = logger or logging.getLogger("fastmcp.retry")

    def _should_retry(self, error: Exception) -> bool:
        """Determine if an error should trigger a retry.

        Checks both the error itself and its ``__cause__``, since FastMCP
        wraps tool exceptions as ``ToolError(...) from original``. Only one
        level of cause is inspected — middleware below this one must not
        re-wrap errors with a new ``from`` clause, or the real type will be
        hidden from the retry decision.
        """
        pass

    def _calculate_delay(self, attempt: int) -> float:
        """Calculate delay for the given attempt number."""
        pass

    async def on_request(self, context: MiddlewareContext, call_next: CallNext) -> Any:
        """Implement retry logic for requests."""
        pass
