"""OAuth Proxy Provider for FastMCP.

This provider acts as a transparent proxy to an upstream OAuth Authorization Server,
handling Dynamic Client Registration locally while forwarding all other OAuth flows.
This enables authentication with upstream providers that don't support DCR or have
restricted client registration policies.

Key features:
- Proxies authorization and token endpoints to upstream server
- Implements local Dynamic Client Registration with fixed upstream credentials
- Validates tokens using upstream JWKS
- Maintains minimal local state for bookkeeping
- Enhanced logging with request correlation

This implementation is based on the OAuth 2.1 specification and is designed for
production use with enterprise identity providers.
"""

from __future__ import annotations

import hashlib
import secrets
import time
from base64 import urlsafe_b64encode
from typing import Any, Literal
from urllib.parse import urlencode, urlparse, urlunparse

import anyio
import httpx
from authlib.common.security import generate_token
from authlib.integrations.httpx_client import AsyncOAuth2Client
from cryptography.fernet import Fernet
from key_value.aio.adapters.pydantic import PydanticAdapter
from key_value.aio.protocols import AsyncKeyValue
from key_value.aio.stores.filetree import (
    FileTreeStore,
    FileTreeV1CollectionSanitizationStrategy,
    FileTreeV1KeySanitizationStrategy,
)
from key_value.aio.wrappers.encryption import FernetEncryptionWrapper
from mcp.server.auth.handlers.metadata import MetadataHandler
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    RefreshToken,
    TokenError,
)
from mcp.server.auth.routes import build_metadata, cors_middleware
from mcp.server.auth.settings import (
    ClientRegistrationOptions,
    RevocationOptions,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from pydantic import AnyHttpUrl, AnyUrl, SecretStr
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse
from starlette.routing import Route
from typing_extensions import override

from fastmcp import settings
from fastmcp.server.auth.auth import (
    OAuthProvider,
    PrivateKeyJWTClientAuthenticator,
    TokenHandler,
    TokenVerifier,
)
from fastmcp.server.auth.cimd import CIMDClientManager
from fastmcp.server.auth.handlers.authorize import AuthorizationHandler
from fastmcp.server.auth.jwt_issuer import (
    JWTIssuer,
    derive_jwt_key,
)
from fastmcp.server.auth.oauth_proxy.consent import ConsentMixin
from fastmcp.server.auth.oauth_proxy.models import (
    DEFAULT_ACCESS_TOKEN_EXPIRY_NO_REFRESH_SECONDS,
    DEFAULT_ACCESS_TOKEN_EXPIRY_SECONDS,
    DEFAULT_AUTH_CODE_EXPIRY_SECONDS,
    HTTP_TIMEOUT_SECONDS,
    ClientCode,
    JTIMapping,
    OAuthTransaction,
    ProxyDCRClient,
    RefreshTokenMetadata,
    UpstreamTokenSet,
    _hash_token,
)
from fastmcp.server.auth.oauth_proxy.ui import create_error_html
from fastmcp.utilities.auth import parse_scopes
from fastmcp.utilities.logging import get_logger

logger = get_logger(__name__)


def _normalize_resource_url(url: str) -> str:
    """Normalize a resource URL by removing query parameters and trailing slashes.

    RFC 8707 allows clients to include query parameters in resource URLs, but the
    server's configured resource URL typically doesn't include them. This function
    normalizes URLs for comparison by stripping query params and fragments.

    Args:
        url: The URL to normalize

    Returns:
        Normalized URL with scheme, host, and path only (no query/fragment)
    """
    parsed = urlparse(str(url))
    return urlunparse(
        (parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", "", "")
    )


def _server_url_has_query(url: str) -> bool:
    """Check if a URL has query parameters."""
    return bool(urlparse(str(url)).query)


class OAuthProxy(OAuthProvider, ConsentMixin):
    """OAuth provider that presents a DCR-compliant interface while proxying to non-DCR IDPs.

    Purpose
    -------
    MCP clients expect OAuth providers to support Dynamic Client Registration (DCR),
    where clients can register themselves dynamically and receive unique credentials.
    Most enterprise IDPs (Google, GitHub, Azure AD, etc.) don't support DCR and require
    pre-registered OAuth applications with fixed credentials.

    This proxy bridges that gap by:
    - Presenting a full DCR-compliant OAuth interface to MCP clients
    - Translating DCR registration requests to use pre-configured upstream credentials
    - Proxying all OAuth flows to the upstream IDP with appropriate translations
    - Managing the state and security requirements of both protocols

    Architecture Overview
    --------------------
    The proxy maintains a single OAuth app registration with the upstream provider
    while allowing unlimited MCP clients to register and authenticate dynamically.
    It implements the complete OAuth 2.1 + DCR specification for clients while
    translating to whatever OAuth variant the upstream provider requires.

    Key Translation Challenges Solved
    ---------------------------------
    1. Dynamic Client Registration:
       - MCP clients expect to register dynamically and get unique credentials
       - Upstream IDPs require pre-registered apps with fixed credentials
       - Solution: Accept DCR requests, return shared upstream credentials

    2. Dynamic Redirect URIs:
       - MCP clients use random localhost ports that change between sessions
       - Upstream IDPs require fixed, pre-registered redirect URIs
       - Solution: Use proxy's fixed callback URL with upstream, forward to client's dynamic URI

    3. Authorization Code Mapping:
       - Upstream returns codes for the proxy's redirect URI
       - Clients expect codes for their own redirect URIs
       - Solution: Exchange upstream code server-side, issue new code to client

    4. State Parameter Collision:
       - Both client and proxy need to maintain state through the flow
       - Only one state parameter available in OAuth
       - Solution: Use transaction ID as state with upstream, preserve client's state

    5. Token Management:
       - Clients may expect different token formats/claims than upstream provides
       - Need to track tokens for revocation and refresh
       - Solution: Store token relationships, forward upstream tokens transparently

    OAuth Flow Implementation
    ------------------------
    1. Client Registration (DCR):
       - Accept any client registration request
       - Store ProxyDCRClient that accepts dynamic redirect URIs

    2. Authorization:
       - Store transaction mapping client details to proxy flow
       - Redirect to upstream with proxy's fixed redirect URI
       - Use transaction ID as state parameter with upstream

    3. Upstream Callback:
       - Exchange upstream authorization code for tokens (server-side)
       - Generate new authorization code bound to client's PKCE challenge
       - Redirect to client's original dynamic redirect URI

    4. Token Exchange:
       - Validate client's code and PKCE verifier
       - Return previously obtained upstream tokens
       - Clean up one-time use authorization code

    5. Token Refresh:
       - Forward refresh requests to upstream using authlib
       - Handle token rotation if upstream issues new refresh token
       - Update local token mappings

    State Management
    ---------------
    The proxy maintains minimal but crucial state via pluggable storage (client_storage):
    - _oauth_transactions: Active authorization flows with client context
    - _client_codes: Authorization codes with PKCE challenges and upstream tokens
    - _jti_mapping_store: Maps FastMCP token JTIs to upstream token IDs
    - _refresh_token_store: Refresh token metadata (keyed by token hash)

    All state is stored in the configured client_storage backend (Redis, disk, etc.)
    enabling horizontal scaling across multiple instances.

    Security Considerations
    ----------------------
    - Refresh tokens stored by hash only (defense in depth if storage compromised)
    - PKCE enforced end-to-end (client to proxy, proxy to upstream)
    - Authorization codes are single-use with short expiry
    - Transaction IDs are cryptographically random
    - All state is cleaned up after use to prevent replay
    - Token validation delegates to upstream provider

    Provider Compatibility
    ---------------------
    Works with any OAuth 2.0 provider that supports:
    - Authorization code flow
    - Fixed redirect URI (configured in provider's app settings)
    - Standard token endpoint

    Handles provider-specific requirements:
    - Google: Ensures minimum scope requirements
    - GitHub: Compatible with OAuth Apps and GitHub Apps
    - Azure AD: Handles tenant-specific endpoints
    - Generic: Works with any spec-compliant provider
    """

    def __init__(
        self,
        *,
        # Upstream server configuration
        upstream_authorization_endpoint: str,
        upstream_token_endpoint: str,
        upstream_client_id: str,
        upstream_client_secret: str | None = None,
        upstream_revocation_endpoint: str | None = None,
        # Token validation
        token_verifier: TokenVerifier,
        # FastMCP server configuration
        base_url: AnyHttpUrl | str,
        resource_base_url: AnyHttpUrl | str | None = None,
        redirect_path: str | None = None,
        issuer_url: AnyHttpUrl | str | None = None,
        service_documentation_url: AnyHttpUrl | str | None = None,
        # Client redirect URI validation
        allowed_client_redirect_uris: list[str] | None = None,
        valid_scopes: list[str] | None = None,
        # PKCE configuration
        forward_pkce: bool = True,
        # Resource indicator (RFC 8707)
        forward_resource: bool = True,
        # Token endpoint authentication
        token_endpoint_auth_method: str | None = None,
        # Extra parameters to forward to authorization endpoint
        extra_authorize_params: dict[str, str] | None = None,
        # Extra parameters to forward to token endpoint
        extra_token_params: dict[str, str] | None = None,
        # Client storage
        client_storage: AsyncKeyValue | None = None,
        # JWT signing key
        jwt_signing_key: str | bytes | None = None,
        # Consent screen configuration
        require_authorization_consent: bool | Literal["external"] = True,
        consent_csp_policy: str | None = None,
        # Token expiry fallback
        fallback_access_token_expiry_seconds: int | None = None,
        # CIMD (Client ID Metadata Document) support
        enable_cimd: bool = True,
    ):
        """Initialize the OAuth proxy provider.

        Args:
            upstream_authorization_endpoint: URL of upstream authorization endpoint
            upstream_token_endpoint: URL of upstream token endpoint
            upstream_client_id: Client ID registered with upstream server
            upstream_client_secret: Client secret for upstream server. Optional for
                PKCE public clients or when using alternative credentials (e.g.,
                managed identity). When omitted, jwt_signing_key must be provided.
            upstream_revocation_endpoint: Optional upstream revocation endpoint
            token_verifier: Token verifier for validating access tokens
            base_url: Public URL of the server that exposes this FastMCP server; redirect path is
                relative to this URL
            resource_base_url: Optional public base URL for the protected resource metadata
                and token audience. Defaults to ``base_url``.
            redirect_path: Redirect path configured in upstream OAuth app (defaults to "/auth/callback")
            issuer_url: Issuer URL for OAuth metadata (defaults to base_url)
            service_documentation_url: Optional service documentation URL
            allowed_client_redirect_uris: List of allowed redirect URI patterns for MCP clients.
                Patterns support wildcards (e.g., "http://localhost:*", "https://*.example.com/*").
                If None (default), all redirect URIs are allowed (for DCR compatibility).
                If empty list, no redirect URIs are allowed.
                These are for MCP clients performing loopback redirects, NOT for the upstream OAuth app.
            valid_scopes: List of all the possible valid scopes for a client.
                These are advertised to clients through the `/.well-known` endpoints. Defaults to `required_scopes` if not provided.
            forward_pkce: Whether to forward PKCE to upstream server (default True).
                Enable for providers that support/require PKCE (Google, Azure, AWS, etc.).
                Disable only if upstream provider doesn't support PKCE.
            token_endpoint_auth_method: Token endpoint authentication method for upstream server.
                Common values: "client_secret_basic", "client_secret_post", "none".
                If None, authlib will use its default (typically "client_secret_basic").
            extra_authorize_params: Additional parameters to forward to the upstream authorization endpoint.
                Useful for provider-specific parameters like Auth0's "audience".
                Example: {"audience": "https://api.example.com"}
            extra_token_params: Additional parameters to forward to the upstream token endpoint.
                Useful for provider-specific parameters during token exchange.
            client_storage: Storage backend for OAuth state (client registrations, tokens).
                If None, an encrypted file store will be created in the data directory.
            jwt_signing_key: Secret for signing FastMCP JWT tokens (any string or bytes).
                If bytes are provided, they will be used as-is.
                If a string is provided, it will be derived into a 32-byte key using PBKDF2 (1.2M iterations).
                If not provided, it will be derived from the upstream client secret using HKDF.
            require_authorization_consent: Whether to require user consent before authorizing clients (default True).
                When True, users see a consent screen before being redirected to the upstream IdP.
                When False, authorization proceeds directly without user confirmation.
                When "external", the built-in consent screen is skipped but no warning is
                logged, indicating that consent is handled externally (e.g. by the upstream IdP).
                SECURITY WARNING: Only set to False for local development or testing environments.
            consent_csp_policy: Content Security Policy for the consent page.
                If None (default), uses the built-in CSP policy with appropriate directives.
                If empty string "", disables CSP entirely (no meta tag is rendered).
                If a non-empty string, uses that as the CSP policy value.
                This allows organizations with their own CSP policies to override or disable
                the built-in CSP directives.
            fallback_access_token_expiry_seconds: Expiry time to use when upstream provider
                doesn't return `expires_in` in the token response. If not set, uses smart
                defaults: 1 hour if a refresh token is available (since we can refresh),
                or 1 year if no refresh token (for API-key-style tokens like GitHub OAuth Apps).
                Set explicitly to override these defaults.
            enable_cimd: Enable CIMD (Client ID Metadata Document) support for URL-based
                client IDs. When True, clients can authenticate using HTTPS URLs as client
                IDs, with metadata fetched from the URL. Supports private_key_jwt auth.
        """

        # Always enable DCR since we implement it locally for MCP clients
        client_registration_options = ClientRegistrationOptions(
            enabled=True,
            valid_scopes=valid_scopes or token_verifier.required_scopes,
        )

        # Enable revocation only if upstream endpoint provided
        revocation_options = (
            RevocationOptions(enabled=True) if upstream_revocation_endpoint else None
        )

        super().__init__(
            base_url=base_url,
            resource_base_url=resource_base_url,
            issuer_url=issuer_url,
            service_documentation_url=service_documentation_url,
            client_registration_options=client_registration_options,
            revocation_options=revocation_options,
            required_scopes=token_verifier.required_scopes,
        )

        # Store upstream configuration
        self._upstream_authorization_endpoint: str = upstream_authorization_endpoint
        self._upstream_token_endpoint: str = upstream_token_endpoint
        self._upstream_client_id: str = upstream_client_id
        self._upstream_client_secret: SecretStr | None = (
            SecretStr(secret_value=upstream_client_secret)
            if upstream_client_secret is not None
            else None
        )
        self._upstream_revocation_endpoint: str | None = upstream_revocation_endpoint
        self._default_scope_str: str = " ".join(
            valid_scopes or self.required_scopes or []
        )

        # Store redirect configuration
        if not redirect_path:
            self._redirect_path = "/auth/callback"
        else:
            self._redirect_path = (
                redirect_path if redirect_path.startswith("/") else f"/{redirect_path}"
            )

        if (
            isinstance(allowed_client_redirect_uris, list)
            and not allowed_client_redirect_uris
        ):
            logger.warning(
                "allowed_client_redirect_uris is empty list; no redirect URIs will be accepted. "
                "This will block all OAuth clients."
            )
        self._allowed_client_redirect_uris: list[str] | None = (
            allowed_client_redirect_uris
        )

        # PKCE configuration
        self._forward_pkce: bool = forward_pkce
        # Resource indicator (RFC 8707)
        self._forward_resource: bool = forward_resource

        # Token endpoint authentication
        self._token_endpoint_auth_method: str | None = token_endpoint_auth_method

        # Consent screen configuration
        self._require_authorization_consent: bool | Literal["external"] = (
            require_authorization_consent
        )
        self._consent_csp_policy: str | None = consent_csp_policy
        if require_authorization_consent == "external":
            logger.info(
                "Built-in consent screen disabled; consent is handled externally."
            )
        elif not require_authorization_consent:
            logger.warning(
                "Authorization consent screen disabled - only use for local development or testing. "
                "In production, this screen protects against confused deputy attacks."
            )

        # Extra parameters for authorization and token endpoints
        self._extra_authorize_params: dict[str, str] = extra_authorize_params or {}
        self._extra_token_params: dict[str, str] = extra_token_params or {}

        # Token expiry fallback (None means use smart default based on refresh token)
        self._fallback_access_token_expiry_seconds: int | None = (
            fallback_access_token_expiry_seconds
        )

        if jwt_signing_key is None:
            if upstream_client_secret is None:
                raise ValueError(
                    "jwt_signing_key is required when upstream_client_secret is not provided. "
                    "The JWT signing key cannot be derived without a client secret."
                )
            jwt_signing_key = derive_jwt_key(
                high_entropy_material=upstream_client_secret,
                salt="fastmcp-jwt-signing-key",
            )

        if isinstance(jwt_signing_key, str):
            if len(jwt_signing_key) < 12:
                logger.warning(
                    "jwt_signing_key is less than 12 characters; it is recommended to use a longer. "
                    "string for the key derivation."
                )
            jwt_signing_key = derive_jwt_key(
                low_entropy_material=jwt_signing_key,
                salt="fastmcp-jwt-signing-key",
            )

        # Store JWT signing key for deferred JWTIssuer creation in set_mcp_path()
        self._jwt_signing_key: bytes = jwt_signing_key
        # JWTIssuer will be created in set_mcp_path() with correct audience
        self._jwt_issuer: JWTIssuer | None = None

        # If the user does not provide a store, we will provide an encrypted file store.
        # The storage directory is derived from the encryption key so that different
        # keys get isolated directories (e.g. two servers on the same machine with
        # different keys won't collide). Decryption errors are treated as cache misses
        # rather than hard failures, so key rotation just causes re-registration.
        if client_storage is None:
            storage_encryption_key = derive_jwt_key(
                high_entropy_material=jwt_signing_key.decode(),
                salt="fastmcp-storage-encryption-key",
            )

            key_fingerprint = hashlib.sha256(storage_encryption_key).hexdigest()[:12]
            storage_dir = settings.home / "oauth-proxy" / key_fingerprint
            storage_dir.mkdir(parents=True, exist_ok=True)

            file_store = FileTreeStore(
                data_directory=storage_dir,
                key_sanitization_strategy=FileTreeV1KeySanitizationStrategy(
                    storage_dir
                ),
                collection_sanitization_strategy=FileTreeV1CollectionSanitizationStrategy(
                    storage_dir
                ),
            )

            client_storage = FernetEncryptionWrapper(
                key_value=file_store,
                fernet=Fernet(key=storage_encryption_key),
                raise_on_decryption_error=False,
            )

        self._client_storage: AsyncKeyValue = client_storage

        # Cache HTTPS check to avoid repeated logging
        self._is_https: bool = str(self.base_url).startswith("https://")
        if not self._is_https:
            logger.warning(
                "Using non-secure cookies for development; deploy with HTTPS for production."
            )

        self._upstream_token_store: PydanticAdapter[UpstreamTokenSet] = PydanticAdapter[
            UpstreamTokenSet
        ](
            key_value=self._client_storage,
            pydantic_model=UpstreamTokenSet,
            default_collection="mcp-upstream-tokens",
            raise_on_validation_error=True,
        )

        self._client_store: PydanticAdapter[ProxyDCRClient] = PydanticAdapter[
            ProxyDCRClient
        ](
            key_value=self._client_storage,
            pydantic_model=ProxyDCRClient,
            default_collection="mcp-oauth-proxy-clients",
            raise_on_validation_error=True,
        )

        # OAuth transaction storage for IdP callback forwarding
        # Reuse client_storage with different collections for state management
        self._transaction_store: PydanticAdapter[OAuthTransaction] = PydanticAdapter[
            OAuthTransaction
        ](
            key_value=self._client_storage,
            pydantic_model=OAuthTransaction,
            default_collection="mcp-oauth-transactions",
            raise_on_validation_error=True,
        )

        self._code_store: PydanticAdapter[ClientCode] = PydanticAdapter[ClientCode](
            key_value=self._client_storage,
            pydantic_model=ClientCode,
            default_collection="mcp-authorization-codes",
            raise_on_validation_error=True,
        )

        # Storage for JTI mappings (FastMCP token -> upstream token)
        self._jti_mapping_store: PydanticAdapter[JTIMapping] = PydanticAdapter[
            JTIMapping
        ](
            key_value=self._client_storage,
            pydantic_model=JTIMapping,
            default_collection="mcp-jti-mappings",
            raise_on_validation_error=True,
        )

        # Refresh token metadata storage, keyed by token hash for security.
        # We only store metadata (not the token itself) - if storage is compromised,
        # attackers get hashes they can't reverse into usable tokens.
        self._refresh_token_store: PydanticAdapter[RefreshTokenMetadata] = (
            PydanticAdapter[RefreshTokenMetadata](
                key_value=self._client_storage,
                pydantic_model=RefreshTokenMetadata,
                default_collection="mcp-refresh-tokens",
                raise_on_validation_error=True,
            )
        )

        # Use the provided token validator
        self._token_validator: TokenVerifier = token_verifier

        # CIMD (Client ID Metadata Document) support
        self._cimd_manager: CIMDClientManager | None = None
        if enable_cimd:
            self._cimd_manager = CIMDClientManager(
                enable_cimd=True,
                default_scope=self._default_scope_str,
                allowed_redirect_uri_patterns=self._allowed_client_redirect_uris,
            )

        # Advisory locks for transparent upstream token refresh, keyed by
        # upstream_token_id. Prevents concurrent async tasks from racing to
        # refresh the same token within a single process. Does not protect
        # against cross-process races in distributed deployments — those are
        # handled by re-reading from storage after refresh failure.
        self._refresh_locks: dict[str, anyio.Lock] = {}

        logger.debug(
            "Initialized OAuth proxy provider with upstream server %s",
            self._upstream_authorization_endpoint,
        )

    # -------------------------------------------------------------------------
    # MCP Path Configuration
    # -------------------------------------------------------------------------

    def set_mcp_path(self, mcp_path: str | None) -> None:
        """Set the MCP endpoint path and create JWTIssuer with correct audience.

        This method is called by get_routes() to configure the resource URL
        and create the JWTIssuer. The JWT audience is set to the full resource
        URL (e.g., http://localhost:8000/mcp) to ensure tokens are bound to
        this specific MCP endpoint.

        Args:
            mcp_path: The path where the MCP endpoint is mounted (e.g., "/mcp")
        """
        super().set_mcp_path(mcp_path)

        # Create JWT issuer with correct audience based on actual MCP path
        # This ensures tokens are bound to the specific resource URL
        self._jwt_issuer = JWTIssuer(
            issuer=str(self.base_url),
            audience=str(self._resource_url),
            signing_key=self._jwt_signing_key,
        )

        logger.debug("Configured OAuth proxy for resource URL: %s", self._resource_url)

    @property
    def jwt_issuer(self) -> JWTIssuer:
        """Get the JWT issuer, ensuring it has been initialized.

        The JWT issuer is created when set_mcp_path() is called (via get_routes()).
        This property ensures a clear error if used before initialization.
        """
        pass

    # -------------------------------------------------------------------------
    # Upstream OAuth Client
    # -------------------------------------------------------------------------

    def _create_upstream_oauth_client(self) -> AsyncOAuth2Client:
        """Create an OAuth2 client for communicating with the upstream IdP.

        This is the single point for constructing the client used in token
        exchange, refresh, and other upstream interactions. Subclasses can
        override this to provide alternative authentication methods (e.g.,
        managed-identity client assertions instead of a static client secret).
        """
        pass

    # -------------------------------------------------------------------------
    # PKCE Helper Methods
    # -------------------------------------------------------------------------

    def _generate_pkce_pair(self) -> tuple[str, str]:
        """Generate PKCE code verifier and challenge pair.

        Returns:
            Tuple of (code_verifier, code_challenge) using S256 method
        """
        pass

    # -------------------------------------------------------------------------
    # Client Registration (Local Implementation)
    # -------------------------------------------------------------------------

    @override
    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        """Get client information by ID. This is generally the random ID
        provided to the DCR client during registration, not the upstream client ID.

        For unregistered clients, returns None (which will raise an error in the SDK).
        CIMD clients (URL-based client IDs) are looked up and cached automatically.
        """
        pass

    @override
    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        """Register a client locally

        When a client registers, we create a ProxyDCRClient that is more
        forgiving about validating redirect URIs, since the DCR client's
        redirect URI will likely be localhost or unknown to the proxied IDP. The
        proxied IDP only knows about this server's fixed redirect URI.
        """
        pass

    # -------------------------------------------------------------------------
    # Authorization Flow (Proxy to Upstream)
    # -------------------------------------------------------------------------

    @override
    async def authorize(
        self,
        client: OAuthClientInformationFull,
        params: AuthorizationParams,
    ) -> str:
        """Start OAuth transaction and route through consent interstitial.

        Flow:
        1. Validate client's resource matches server's resource URL (security check)
        2. Store transaction with client details and PKCE (if forwarding)
        3. Return local /consent URL; browser visits consent first
        4. Consent handler redirects to upstream IdP if approved/already approved

        If consent is disabled (require_authorization_consent=False), skip the consent screen
        and redirect directly to the upstream IdP.
        """
        pass

    # -------------------------------------------------------------------------
    # Authorization Code Handling
    # -------------------------------------------------------------------------

    @override
    async def load_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: str,
    ) -> AuthorizationCode | None:
        """Load authorization code for validation.

        Look up our client code and return authorization code object
        with PKCE challenge for validation.
        """
        pass

    @override
    async def exchange_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: AuthorizationCode,
    ) -> OAuthToken:
        """Exchange authorization code for FastMCP-issued tokens.

        Implements the token factory pattern:
        1. Retrieves upstream tokens from stored authorization code
        2. Extracts user identity from upstream token
        3. Encrypts and stores upstream tokens
        4. Issues FastMCP-signed JWT tokens
        5. Returns FastMCP tokens (NOT upstream tokens)

        PKCE validation is handled by the MCP framework before this method is called.
        """
        pass

    # -------------------------------------------------------------------------
    # Refresh Token Flow
    # -------------------------------------------------------------------------

    def _prepare_scopes_for_token_exchange(self, scopes: list[str]) -> list[str]:
        """Prepare scopes for initial token exchange (auth code -> tokens).

        Override this method to provide scopes during the authorization
        code exchange. Some providers (like Azure) require scopes to be sent.

        Args:
            scopes: Scopes from the authorization request

        Returns:
            List of scopes to send, or empty list to omit scope parameter
        """
        pass

    def _prepare_scopes_for_upstream_refresh(self, scopes: list[str]) -> list[str]:
        """Prepare scopes for upstream token refresh request.

        Override this method to transform scopes before sending to upstream provider.
        For example, Azure needs to prefix scopes and add additional Graph scopes.

        The scopes parameter represents what should be stored in the RefreshToken.
        This method returns what should be sent to the upstream provider.

        Args:
            scopes: Base scopes that will be stored in RefreshToken

        Returns:
            Scopes to send to upstream provider (may be transformed/augmented)
        """
        pass

    async def _extract_upstream_claims(
        self, idp_tokens: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Extract upstream claims to embed in FastMCP JWT.

        Override this method to decode upstream tokens, call userinfo endpoints,
        or otherwise extract claims that should be embedded in the FastMCP JWT
        issued to MCP clients. This enables gateways to inspect upstream identity
        information by decoding the JWT without server-side storage lookups.

        Args:
            idp_tokens: Full token response from upstream provider. Contains
                access_token, and for OIDC providers may include id_token,
                refresh_token, and other response fields.

        Returns:
            Dict of claims to embed in JWT under the "upstream_claims" key,
            or None to not embed any upstream claims.

        Example:
            For Azure/Entra ID, you might decode the access_token JWT and
            extract claims like sub, oid, name, preferred_username, email,
            roles, and groups.
        """
        pass

    async def load_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: str,
    ) -> RefreshToken | None:
        """Load refresh token metadata from distributed storage.

        Looks up by token hash and reconstructs the RefreshToken object.
        Validates that the token belongs to the requesting client.
        """
        pass

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        """Exchange FastMCP refresh token for new FastMCP access token.

        Implements two-tier refresh:
        1. Verify FastMCP refresh token
        2. Look up upstream token via JTI mapping
        3. Refresh upstream token with upstream provider
        4. Update stored upstream token
        5. Issue new FastMCP access token
        6. Keep same FastMCP refresh token (unless upstream rotates)
        """
        pass

    # -------------------------------------------------------------------------
    # Token Validation
    # -------------------------------------------------------------------------

    def _get_verification_token(
        self, upstream_token_set: UpstreamTokenSet
    ) -> str | None:
        """Get the token string to pass to the token verifier.

        Returns the upstream access token by default. Subclasses can override
        to verify a different token (e.g., the OIDC id_token for providers
        that issue opaque access tokens).
        """
        pass

    def _uses_alternate_verification(self) -> bool:
        """Whether this provider verifies a different token than the access token.

        When True, ``load_access_token`` patches the validated result with
        the upstream access token, scopes, and expiry so that the returned
        ``AccessToken`` reflects the access token rather than the
        verification token.

        The default implementation compares token values, but subclasses
        should override this to use an intent-based flag so the patch is
        applied even when the verification token and access token happen to
        carry the same value (e.g., some OIDC providers issue identical
        JWTs for both).
        """
        pass

    async def _try_transparent_refresh(
        self,
        upstream_token_set: UpstreamTokenSet,
    ) -> UpstreamTokenSet:
        """Refresh the upstream token transparently and update storage.

        Called during load_access_token when the upstream token has expired
        but a refresh token is available. This avoids returning a 401 that
        would force the client into a full re-authentication flow.

        Mutates and returns the upstream_token_set with refreshed token data.
        Raises on failure (caller should catch and fall through to None).
        """
        pass

    async def load_access_token(self, token: str) -> AccessToken | None:  # type: ignore[override]  # ty:ignore[invalid-method-override]
        """Validate FastMCP JWT by swapping for upstream token.

        This implements the token swap pattern:
        1. Verify FastMCP JWT signature (proves it's our token)
        2. Look up upstream token via JTI mapping
        3. Decrypt upstream token
        4. Validate upstream token with provider (GitHub API, JWT validation, etc.)
        5. If upstream validation fails, attempt transparent refresh
        6. Return upstream validation result

        The FastMCP JWT is a reference token - all authorization data comes
        from validating the upstream token via the TokenVerifier.
        """
        pass

    # -------------------------------------------------------------------------
    # Token Revocation
    # -------------------------------------------------------------------------

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        """Revoke token locally and with upstream server if supported.

        For refresh tokens, removes from local storage by hash.
        For all tokens, attempts upstream revocation if endpoint is configured.
        Access token JTI mappings expire via TTL.
        """
        pass

    def get_routes(
        self,
        mcp_path: str | None = None,
    ) -> list[Route]:
        """Get OAuth routes with custom handlers for better error UX.

        This method creates standard OAuth routes and replaces:
        - /authorize endpoint: Enhanced error responses for unregistered clients
        - /token endpoint: OAuth 2.1 compliant error codes

        Args:
            mcp_path: The path where the MCP endpoint is mounted (e.g., "/mcp")
                This is used to advertise the resource URL in metadata.
        """
        # Get standard OAuth routes from parent class
        # Note: parent already replaces /token with TokenHandler for proper error codes
        routes = super().get_routes(mcp_path)
        custom_routes = []

        logger.debug(
            f"get_routes called - configuring OAuth routes in {len(routes)} routes"
        )

        for i, route in enumerate(routes):
            logger.debug(
                f"Route {i}: {route} - path: {getattr(route, 'path', 'N/A')}, methods: {getattr(route, 'methods', 'N/A')}"
            )

            # Replace the authorize endpoint with our enhanced handler for better error UX
            if (
                isinstance(route, Route)
                and route.path == "/authorize"
                and route.methods is not None
                and ("GET" in route.methods or "POST" in route.methods)
            ):
                # Replace with our enhanced authorization handler
                # Note: self.base_url is guaranteed to be set in parent __init__
                authorize_handler = AuthorizationHandler(
                    provider=self,
                    base_url=self.base_url,  # ty: ignore[invalid-argument-type]
                    server_name=None,  # Could be extended to pass server metadata
                    server_icon_url=None,
                )
                custom_routes.append(
                    Route(
                        path="/authorize",
                        endpoint=authorize_handler.handle,
                        methods=["GET", "POST"],
                    )
                )
            elif (
                self._cimd_manager is not None
                and isinstance(route, Route)
                and route.path == "/token"
                and route.methods is not None
                and "POST" in route.methods
            ):
                # Replace the token endpoint authenticator with one that supports
                # private_key_jwt for CIMD clients
                token_endpoint_url = f"{self.base_url}/token"
                cimd_authenticator = PrivateKeyJWTClientAuthenticator(
                    provider=self,
                    cimd_manager=self._cimd_manager,
                    token_endpoint_url=token_endpoint_url,
                )
                token_handler = TokenHandler(
                    provider=self, client_authenticator=cimd_authenticator
                )
                custom_routes.append(
                    Route(
                        path="/token",
                        endpoint=cors_middleware(
                            token_handler.handle, ["POST", "OPTIONS"]
                        ),
                        methods=["POST", "OPTIONS"],
                    )
                )
            elif (
                self._cimd_manager is not None
                and isinstance(route, Route)
                and route.path.startswith("/.well-known/oauth-authorization-server")
            ):
                client_registration_options = (
                    self.client_registration_options or ClientRegistrationOptions()
                )
                revocation_options = self.revocation_options or RevocationOptions()
                metadata = build_metadata(
                    self.base_url,  # ty: ignore[invalid-argument-type]
                    self.service_documentation_url,
                    client_registration_options,
                    revocation_options,
                )
                metadata.client_id_metadata_document_supported = True
                handler = MetadataHandler(metadata)
                methods = route.methods or ["GET", "OPTIONS"]

                custom_routes.append(
                    Route(
                        path=route.path,
                        endpoint=cors_middleware(handler.handle, ["GET", "OPTIONS"]),
                        methods=methods,
                        name=route.name,
                        include_in_schema=route.include_in_schema,
                    )
                )
            else:
                # Keep all other standard OAuth routes unchanged
                custom_routes.append(route)

        # Add OAuth callback endpoint for forwarding to client callbacks
        custom_routes.append(
            Route(
                path=self._redirect_path,
                endpoint=self._handle_idp_callback,
                methods=["GET"],
            )
        )

        # Add consent endpoints
        # Handle both GET (show page) and POST (submit) at /consent
        custom_routes.append(
            Route(
                path="/consent", endpoint=self._handle_consent, methods=["GET", "POST"]
            )
        )

        return custom_routes

    # -------------------------------------------------------------------------
    # IdP Callback Forwarding
    # -------------------------------------------------------------------------

    async def _handle_idp_callback(
        self, request: Request
    ) -> HTMLResponse | RedirectResponse:
        """Handle callback from upstream IdP and forward to client.

        This implements the DCR-compliant callback forwarding:
        1. Receive IdP callback with code and txn_id as state
        2. Exchange IdP code for tokens (server-side)
        3. Generate our own client code bound to PKCE challenge
        4. Redirect to client's callback with client code and original state
        """
        pass
