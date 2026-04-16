"""Enhanced authentication middleware with better error messages.

This module provides enhanced versions of MCP SDK authentication middleware
that return more helpful error messages for developers troubleshooting
authentication issues.
"""

from __future__ import annotations

import json

from mcp.server.auth.middleware.bearer_auth import (
    RequireAuthMiddleware as SDKRequireAuthMiddleware,
)
from starlette.types import Send

from fastmcp.utilities.logging import get_logger

logger = get_logger(__name__)


class RequireAuthMiddleware(SDKRequireAuthMiddleware):
    """Enhanced authentication middleware with detailed error messages.

    Extends the SDK's RequireAuthMiddleware to provide more actionable
    error messages when authentication fails. This helps developers
    understand what went wrong and how to fix it.
    """

    async def _send_auth_error(
        self, send: Send, status_code: int, error: str, description: str
    ) -> None:
        """Send an authentication error response with enhanced error messages.

        Overrides the SDK's _send_auth_error to provide more detailed
        error descriptions that help developers troubleshoot authentication
        issues.

        Args:
            send: ASGI send callable
            status_code: HTTP status code (401 or 403)
            error: OAuth error code
            description: Base error description
        """
        pass
