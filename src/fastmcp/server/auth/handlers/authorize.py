"""Enhanced authorization handler with improved error responses.

This module provides an enhanced authorization handler that wraps the MCP SDK's
AuthorizationHandler to provide better error messages when clients attempt to
authorize with unregistered client IDs.

The enhancement adds:
- Content negotiation: HTML for browsers, JSON for API clients
- Enhanced JSON responses with registration endpoint hints
- Styled HTML error pages with registration links/forms
- Link headers pointing to registration endpoints
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from mcp.server.auth.handlers.authorize import (
    AuthorizationHandler as SDKAuthorizationHandler,
)
from pydantic import AnyHttpUrl
from starlette.requests import Request
from starlette.responses import Response

from fastmcp.utilities.logging import get_logger
from fastmcp.utilities.ui import (
    INFO_BOX_STYLES,
    TOOLTIP_STYLES,
    create_logo,
    create_page,
    create_secure_html_response,
)

if TYPE_CHECKING:
    from mcp.server.auth.provider import OAuthAuthorizationServerProvider

logger = get_logger(__name__)


def create_unregistered_client_html(
    client_id: str,
    registration_endpoint: str,
    discovery_endpoint: str,
    server_name: str | None = None,
    server_icon_url: str | None = None,
    title: str = "Client Not Registered",
) -> str:
    """Create styled HTML error page for unregistered client attempts.

    Args:
        client_id: The unregistered client ID that was provided
        registration_endpoint: URL of the registration endpoint
        discovery_endpoint: URL of the OAuth metadata discovery endpoint
        server_name: Optional server name for branding
        server_icon_url: Optional server icon URL
        title: Page title

    Returns:
        HTML string for the error page
    """
    pass


class AuthorizationHandler(SDKAuthorizationHandler):
    """Authorization handler with enhanced error responses for unregistered clients.

    This handler extends the MCP SDK's AuthorizationHandler to provide better UX
    when clients attempt to authorize without being registered. It implements
    content negotiation to return:

    - HTML error pages for browser requests
    - Enhanced JSON with registration hints for API clients
    - Link headers pointing to registration endpoints

    This maintains OAuth 2.1 compliance (returns 400 for invalid client_id)
    while providing actionable guidance to fix the error.
    """

    def __init__(
        self,
        provider: OAuthAuthorizationServerProvider,
        base_url: AnyHttpUrl | str,
        server_name: str | None = None,
        server_icon_url: str | None = None,
    ):
        """Initialize the enhanced authorization handler.

        Args:
            provider: OAuth authorization server provider
            base_url: Base URL of the server for constructing endpoint URLs
            server_name: Optional server name for branding
            server_icon_url: Optional server icon URL for branding
        """
        super().__init__(provider)
        self._base_url = str(base_url).rstrip("/")
        self._server_name = server_name
        self._server_icon_url = server_icon_url

    async def handle(self, request: Request) -> Response:
        """Handle authorization request with enhanced error responses.

        This method extends the SDK's authorization handler and intercepts
        errors for unregistered clients to provide better error responses
        based on the client's Accept header.

        Args:
            request: The authorization request

        Returns:
            Response (redirect on success, error response on failure)
        """
        pass

    async def _create_enhanced_error_response(
        self, request: Request, client_id: str, state: str | None
    ) -> Response:
        """Create enhanced error response with content negotiation.

        Args:
            request: The original request
            client_id: The unregistered client ID
            state: The state parameter from the request

        Returns:
            HTML or JSON error response based on Accept header
        """
        pass
