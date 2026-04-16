from __future__ import annotations

import time
import webbrowser
from collections.abc import AsyncGenerator
from contextlib import aclosing
from typing import Any

import anyio
import httpx
from key_value.aio.adapters.pydantic import PydanticAdapter
from key_value.aio.protocols import AsyncKeyValue
from key_value.aio.stores.memory import MemoryStore
from mcp.client.auth import OAuthClientProvider, TokenStorage
from mcp.shared._httpx_utils import McpHttpClientFactory
from mcp.shared.auth import (
    OAuthClientInformationFull,
    OAuthClientMetadata,
    OAuthToken,
)
from pydantic import AnyHttpUrl
from typing_extensions import override
from uvicorn.server import Server

from fastmcp.client.oauth_callback import (
    OAuthCallbackResult,
    create_oauth_callback_server,
)
from fastmcp.utilities.http import find_available_port
from fastmcp.utilities.logging import get_logger

__all__ = ["OAuth"]

logger = get_logger(__name__)


class ClientNotFoundError(Exception):
    """Raised when OAuth client credentials are not found on the server."""


async def check_if_auth_required(
    mcp_url: str, httpx_kwargs: dict[str, Any] | None = None
) -> bool:
    """
    Check if the MCP endpoint requires authentication by making a test request.

    Returns:
        True if auth appears to be required, False otherwise
    """
    pass


class TokenStorageAdapter(TokenStorage):
    _server_url: str
    _key_value_store: AsyncKeyValue
    _storage_oauth_token: PydanticAdapter[OAuthToken]
    _storage_client_info: PydanticAdapter[OAuthClientInformationFull]

    def __init__(self, async_key_value: AsyncKeyValue, server_url: str):
        self._server_url = server_url
        self._key_value_store = async_key_value
        self._storage_oauth_token = PydanticAdapter[OAuthToken](
            default_collection="mcp-oauth-token",
            key_value=async_key_value,
            pydantic_model=OAuthToken,
            raise_on_validation_error=True,
        )
        self._storage_client_info = PydanticAdapter[OAuthClientInformationFull](
            default_collection="mcp-oauth-client-info",
            key_value=async_key_value,
            pydantic_model=OAuthClientInformationFull,
            raise_on_validation_error=True,
        )

    def _get_token_cache_key(self) -> str:
        return f"{self._server_url}/tokens"

    def _get_client_info_cache_key(self) -> str:
        return f"{self._server_url}/client_info"

    def _get_token_expiry_cache_key(self) -> str:
        return f"{self._server_url}/token_expiry"

    async def clear(self) -> None:
        await self._storage_oauth_token.delete(key=self._get_token_cache_key())
        await self._storage_client_info.delete(key=self._get_client_info_cache_key())
        await self._key_value_store.delete(
            key=self._get_token_expiry_cache_key(),
            collection="mcp-oauth-token-expiry",
        )

    @override
    async def get_tokens(self) -> OAuthToken | None:
        pass

    @override
    async def set_tokens(self, tokens: OAuthToken) -> None:
        # Don't set TTL based on access token expiry - the refresh token may be
        # valid much longer. Use 1 year as a reasonable upper bound; the OAuth
        # provider handles actual token expiry/refresh logic.
        pass

    async def get_token_expiry(self) -> float | None:
        pass

    @override
    async def get_client_info(self) -> OAuthClientInformationFull | None:
        pass

    @override
    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        pass


class OAuth(OAuthClientProvider):
    """
    OAuth client provider for MCP servers with browser-based authentication.

    This class provides OAuth authentication for FastMCP clients by opening
    a browser for user authorization and running a local callback server.
    """

    _bound: bool

    def __init__(
        self,
        mcp_url: str | None = None,
        scopes: str | list[str] | None = None,
        client_name: str = "FastMCP Client",
        token_storage: AsyncKeyValue | None = None,
        additional_client_metadata: dict[str, Any] | None = None,
        callback_port: int | None = None,
        httpx_client_factory: McpHttpClientFactory | None = None,
        # Alternative to dynamic client registration:
        # --- Clients host a static JSON document at an HTTPS URL ---
        client_metadata_url: str | None = None,
        # --- OR clients provide full client information ---
        client_id: str | None = None,
        client_secret: str | None = None,
    ):
        """
        Initialize OAuth client provider for an MCP server.

        Args:
            mcp_url: Full URL to the MCP endpoint (e.g. "http://host/mcp/sse/").
                Optional when OAuth is passed to Client(auth=...), which provides
                the URL automatically from the transport.
            scopes: OAuth scopes to request. Can be a
            space-separated string or a list of strings.
            client_name: Name for this client during registration
            token_storage: An AsyncKeyValue-compatible token store, tokens are stored in memory if not provided
            additional_client_metadata: Extra fields for OAuthClientMetadata
            callback_port: Fixed port for OAuth callback (default: random available port)
            client_metadata_url: A CIMD (Client ID Metadata Document) URL. When
                provided, this URL is used as the client_id instead of performing
                Dynamic Client Registration. Must be an HTTPS URL with a non-root
                path (e.g. "https://myapp.example.com/oauth/client.json").
            client_id: Pre-registered OAuth client ID. When provided, skips dynamic
                client registration and uses these static credentials instead.
            client_secret: OAuth client secret (optional, used with client_id)
        """
        # Store config for deferred binding if mcp_url not yet known
        self._scopes = scopes
        self._client_name = client_name
        self._token_storage = token_storage
        self._additional_client_metadata = additional_client_metadata
        self._callback_port = callback_port
        self._client_metadata_url = client_metadata_url
        self._client_id = client_id
        self._client_secret = client_secret
        self._static_client_info = None
        self.httpx_client_factory = httpx_client_factory or httpx.AsyncClient
        self._bound = False

        if mcp_url is not None:
            self._bind(mcp_url)

    def _bind(self, mcp_url: str) -> None:
        """Bind this OAuth provider to a specific MCP server URL.

        Called automatically when mcp_url is provided to __init__, or by the
        transport when OAuth is used without an explicit URL.
        """
        pass

    async def _initialize(self) -> None:
        """Load stored tokens and client info, properly setting token expiry."""
        pass

    async def redirect_handler(self, authorization_url: str) -> None:
        """Open browser for authorization, with pre-flight check for invalid client."""
        pass

    async def callback_handler(self) -> tuple[str, str | None]:
        """Handle OAuth callback and return (auth_code, state)."""
        pass

    async def async_auth_flow(
        self, request: httpx.Request
    ) -> AsyncGenerator[httpx.Request, httpx.Response]:
        """HTTPX auth flow with automatic retry on stale cached credentials.

        If the OAuth flow fails due to invalid/stale client credentials,
        clears the cache and retries once with fresh registration.
        """
        pass
