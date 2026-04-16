import secrets
import time

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    RefreshToken,
    TokenError,
    construct_redirect_uri,
)
from mcp.shared.auth import (
    OAuthClientInformationFull,
    OAuthToken,
)
from pydantic import AnyHttpUrl

from fastmcp.server.auth.auth import (
    ClientRegistrationOptions,
    OAuthProvider,
    RevocationOptions,
)

# Default expiration times (in seconds)
DEFAULT_AUTH_CODE_EXPIRY_SECONDS = 5 * 60  # 5 minutes
DEFAULT_ACCESS_TOKEN_EXPIRY_SECONDS = 60 * 60  # 1 hour
DEFAULT_REFRESH_TOKEN_EXPIRY_SECONDS = None  # No expiry


class InMemoryOAuthProvider(OAuthProvider):
    """
    An in-memory OAuth provider for testing purposes.
    It simulates the OAuth 2.1 flow locally without external calls.
    """

    def __init__(
        self,
        base_url: AnyHttpUrl | str | None = None,
        resource_base_url: AnyHttpUrl | str | None = None,
        service_documentation_url: AnyHttpUrl | str | None = None,
        client_registration_options: ClientRegistrationOptions | None = None,
        revocation_options: RevocationOptions | None = None,
        required_scopes: list[str] | None = None,
    ):
        super().__init__(
            base_url=base_url or "http://fastmcp.example.com",
            resource_base_url=resource_base_url,
            service_documentation_url=service_documentation_url,
            client_registration_options=client_registration_options,
            revocation_options=revocation_options,
            required_scopes=required_scopes,
        )
        self.clients: dict[str, OAuthClientInformationFull] = {}
        self.auth_codes: dict[str, AuthorizationCode] = {}
        self.access_tokens: dict[str, AccessToken] = {}
        self.refresh_tokens: dict[str, RefreshToken] = {}

        # For revoking associated tokens
        self._access_to_refresh_map: dict[
            str, str
        ] = {}  # access_token_str -> refresh_token_str
        self._refresh_to_access_map: dict[
            str, str
        ] = {}  # refresh_token_str -> access_token_str

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        pass

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        # Validate scopes against valid_scopes if configured (matches MCP SDK behavior)
        pass

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        """
        Simulates user authorization and generates an authorization code.
        Returns a redirect URI with the code and state.
        """
        pass

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        pass

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        # Authorization code should have been validated (existence, expiry, client_id match)
        # by the TokenHandler calling load_authorization_code before this.
        # We might want to re-verify or simply trust it's valid.

        pass

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> RefreshToken | None:
        pass

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,  # This is the RefreshToken object, already loaded
        scopes: list[str],  # Requested scopes for the new access token
    ) -> OAuthToken:
        # Validate scopes: requested scopes must be a subset of original scopes
        pass

    async def load_access_token(self, token: str) -> AccessToken | None:  # type: ignore[override]  # ty:ignore[invalid-method-override]
        pass

    async def verify_token(self, token: str) -> AccessToken | None:  # type: ignore[override]  # ty:ignore[invalid-method-override]
        """
        Verify a bearer token and return access info if valid.

        This method implements the TokenVerifier protocol by delegating
        to our existing load_access_token method.

        Args:
            token: The token string to validate

        Returns:
            AccessToken object if valid, None if invalid or expired
        """
        pass

    def _revoke_internal(
        self, access_token_str: str | None = None, refresh_token_str: str | None = None
    ):
        """Internal helper to remove tokens and their associations."""
        pass

    async def revoke_token(
        self,
        token: AccessToken | RefreshToken,
    ) -> None:
        """Revokes an access or refresh token and its counterpart."""
        pass
        # If token is not found or already revoked, _revoke_internal does nothing, which is correct.
