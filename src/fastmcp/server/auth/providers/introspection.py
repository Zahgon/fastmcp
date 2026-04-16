"""OAuth 2.0 Token Introspection (RFC 7662) provider for FastMCP.

This module provides token verification for opaque tokens using the OAuth 2.0
Token Introspection protocol defined in RFC 7662. It allows FastMCP servers to
validate tokens issued by authorization servers that don't use JWT format.

Example:
    ```python
    from fastmcp import FastMCP
    from fastmcp.server.auth.providers.introspection import IntrospectionTokenVerifier

    # Verify opaque tokens via RFC 7662 introspection
    verifier = IntrospectionTokenVerifier(
        introspection_url="https://auth.example.com/oauth/introspect",
        client_id="your-client-id",
        client_secret="your-client-secret",
        required_scopes=["read", "write"]
    )

    mcp = FastMCP("My Protected Server", auth=verifier)
    ```
"""

from __future__ import annotations

import base64
import contextlib
import time
from typing import Any, Literal, get_args

import httpx
from pydantic import AnyHttpUrl, SecretStr

from fastmcp.server.auth import AccessToken, TokenVerifier
from fastmcp.utilities.auth import parse_scopes
from fastmcp.utilities.logging import get_logger
from fastmcp.utilities.token_cache import TokenCache

logger = get_logger(__name__)


ClientAuthMethod = Literal["client_secret_basic", "client_secret_post"]


class IntrospectionTokenVerifier(TokenVerifier):
    """
    OAuth 2.0 Token Introspection verifier (RFC 7662).

    This verifier validates opaque tokens by calling an OAuth 2.0 token introspection
    endpoint. Unlike JWT verification which is stateless, token introspection requires
    a network call to the authorization server for each token validation.

    The verifier authenticates to the introspection endpoint using either:
    - HTTP Basic Auth (client_secret_basic, default): credentials in Authorization header
    - POST body authentication (client_secret_post): credentials in request body

    Both methods are specified in RFC 6749 (OAuth 2.0) and RFC 7662 (Token Introspection).

    Use this when:
    - Your authorization server issues opaque (non-JWT) tokens
    - You need to validate tokens from Auth0, Okta, Keycloak, or other OAuth servers
    - Your tokens require real-time revocation checking
    - Your authorization server supports RFC 7662 introspection

    Caching is disabled by default to preserve real-time revocation semantics.
    Set ``cache_ttl_seconds`` to enable caching and reduce load on the
    introspection endpoint (e.g., ``cache_ttl_seconds=300`` for 5 minutes).

    Example:
        ```python
        verifier = IntrospectionTokenVerifier(
            introspection_url="https://auth.example.com/oauth/introspect",
            client_id="my-service",
            client_secret="secret-key",
            required_scopes=["api:read"]
        )
        ```
    """

    def __init__(
        self,
        *,
        introspection_url: str,
        client_id: str,
        client_secret: str | SecretStr,
        client_auth_method: ClientAuthMethod = "client_secret_basic",
        timeout_seconds: int = 10,
        required_scopes: list[str] | None = None,
        base_url: AnyHttpUrl | str | None = None,
        cache_ttl_seconds: int | None = None,
        max_cache_size: int | None = None,
        http_client: httpx.AsyncClient | None = None,
    ):
        """
        Initialize the introspection token verifier.

        Args:
            introspection_url: URL of the OAuth 2.0 token introspection endpoint
            client_id: OAuth client ID for authenticating to the introspection endpoint
            client_secret: OAuth client secret for authenticating to the introspection endpoint
            client_auth_method: Client authentication method. "client_secret_basic" (default)
                uses HTTP Basic Auth header, "client_secret_post" sends credentials in POST body
            timeout_seconds: HTTP request timeout in seconds (default: 10)
            required_scopes: Required scopes for all tokens (optional)
            base_url: Base URL for TokenVerifier protocol
            cache_ttl_seconds: How long to cache introspection results in seconds.
                Caching is disabled by default (None) to preserve real-time
                revocation semantics. Set to a positive integer to enable caching
                (e.g., 300 for 5 minutes).
            max_cache_size: Maximum number of tokens to cache when caching is
                enabled. Default: 10000.
            http_client: Optional httpx.AsyncClient for connection pooling. When provided,
                the client is reused across calls and the caller is responsible for its
                lifecycle. When None (default), a fresh client is created per call.
        """
        # Parse scopes if provided as string
        parsed_required_scopes = (
            parse_scopes(required_scopes) if required_scopes is not None else None
        )

        super().__init__(base_url=base_url, required_scopes=parsed_required_scopes)

        self.introspection_url = introspection_url
        self.client_id = client_id
        self.client_secret = (
            client_secret.get_secret_value()
            if isinstance(client_secret, SecretStr)
            else client_secret
        )

        # Validate client_auth_method to catch typos/invalid values early
        valid_methods = get_args(ClientAuthMethod)
        if client_auth_method not in valid_methods:
            options = " or ".join(f"'{m}'" for m in valid_methods)
            raise ValueError(
                f"Invalid client_auth_method: {client_auth_method!r}. "
                f"Must be {options}."
            )
        self.client_auth_method: ClientAuthMethod = client_auth_method

        self.timeout_seconds = timeout_seconds
        self._http_client = http_client
        self.logger = get_logger(__name__)

        self._cache = TokenCache(
            ttl_seconds=cache_ttl_seconds,
            max_size=max_cache_size,
        )

    def _create_basic_auth_header(self) -> str:
        """Create HTTP Basic Auth header value from client credentials."""
        pass

    def _extract_scopes(self, introspection_response: dict[str, Any]) -> list[str]:
        """
        Extract scopes from introspection response.

        RFC 7662 allows scopes to be returned as either:
        - A space-separated string in the 'scope' field
        - An array of strings in the 'scope' field (less common but valid)
        """
        pass

    async def verify_token(self, token: str) -> AccessToken | None:
        """
        Verify a bearer token using OAuth 2.0 Token Introspection (RFC 7662).

        This method makes a POST request to the introspection endpoint with the token,
        authenticated using the configured client authentication method (client_secret_basic
        or client_secret_post).

        Results are cached in-memory to reduce load on the introspection endpoint.
        Cache TTL and size are configurable via constructor parameters.

        Args:
            token: The opaque token string to validate

        Returns:
            AccessToken object if valid and active, None if invalid, inactive, or expired
        """
        pass
