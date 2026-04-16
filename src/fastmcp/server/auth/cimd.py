"""CIMD (Client ID Metadata Document) support for FastMCP.

.. warning::
    **Beta Feature**: CIMD support is currently in beta. The API may change
    in future releases. Please report any issues you encounter.

CIMD is a simpler alternative to Dynamic Client Registration where clients
host a static JSON document at an HTTPS URL, and that URL becomes their
client_id. See the IETF draft: draft-parecki-oauth-client-id-metadata-document

This module provides:
- CIMDDocument: Pydantic model for CIMD document validation
- CIMDFetcher: Fetch and validate CIMD documents with SSRF protection
- CIMDClientManager: Manages CIMD client operations
"""

from __future__ import annotations

import json
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timezone
from email.utils import parsedate_to_datetime
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import urlparse

from pydantic import AnyHttpUrl, BaseModel, Field, field_validator

from fastmcp.server.auth.redirect_validation import matches_allowed_pattern
from fastmcp.server.auth.ssrf import (
    SSRFError,
    SSRFFetchError,
    ssrf_safe_fetch_response,
    validate_url,
)
from fastmcp.utilities.logging import get_logger

if TYPE_CHECKING:
    from fastmcp.server.auth.providers.jwt import JWTVerifier

logger = get_logger(__name__)


class CIMDDocument(BaseModel):
    """CIMD document per draft-parecki-oauth-client-id-metadata-document.

    The client metadata document is a JSON document containing OAuth client
    metadata. The client_id property MUST match the URL where this document
    is hosted.

    Key constraint: token_endpoint_auth_method MUST NOT use shared secrets
    (client_secret_post, client_secret_basic, client_secret_jwt).

    redirect_uris is required and must contain at least one entry.
    """

    client_id: AnyHttpUrl = Field(
        ...,
        description="Must match the URL where this document is hosted",
    )
    client_name: str | None = Field(
        default=None,
        description="Human-readable name of the client",
    )
    client_uri: AnyHttpUrl | None = Field(
        default=None,
        description="URL of the client's home page",
    )
    logo_uri: AnyHttpUrl | None = Field(
        default=None,
        description="URL of the client's logo image",
    )
    redirect_uris: list[str] = Field(
        ...,
        description="Array of allowed redirect URIs (may include wildcards like http://localhost:*/callback)",
    )
    token_endpoint_auth_method: Literal["none", "private_key_jwt"] = Field(
        default="none",
        description="Authentication method for token endpoint (no shared secrets allowed)",
    )
    grant_types: list[str] = Field(
        default_factory=lambda: ["authorization_code"],
        description="OAuth grant types the client will use",
    )
    response_types: list[str] = Field(
        default_factory=lambda: ["code"],
        description="OAuth response types the client will use",
    )
    scope: str | None = Field(
        default=None,
        description="Space-separated list of scopes the client may request",
    )
    contacts: list[str] | None = Field(
        default=None,
        description="Contact information for the client developer",
    )
    tos_uri: AnyHttpUrl | None = Field(
        default=None,
        description="URL of the client's terms of service",
    )
    policy_uri: AnyHttpUrl | None = Field(
        default=None,
        description="URL of the client's privacy policy",
    )
    jwks_uri: AnyHttpUrl | None = Field(
        default=None,
        description="URL of the client's JSON Web Key Set (for private_key_jwt)",
    )
    jwks: dict[str, Any] | None = Field(
        default=None,
        description="Client's JSON Web Key Set (for private_key_jwt)",
    )
    software_id: str | None = Field(
        default=None,
        description="Unique identifier for the client software",
    )
    software_version: str | None = Field(
        default=None,
        description="Version of the client software",
    )

    @field_validator("token_endpoint_auth_method")
    @classmethod
    def validate_auth_method(cls, v: str) -> str:
        """Ensure no shared-secret auth methods are used."""
        pass

    @field_validator("redirect_uris")
    @classmethod
    def validate_redirect_uris(cls, v: list[str]) -> list[str]:
        """Ensure redirect_uris is non-empty and each entry is a valid URI."""
        pass


class CIMDValidationError(Exception):
    """Raised when CIMD document validation fails."""


class CIMDFetchError(Exception):
    """Raised when CIMD document fetching fails."""


@dataclass
class _CIMDCacheEntry:
    """Cached CIMD document and associated HTTP cache metadata."""

    doc: CIMDDocument
    etag: str | None
    last_modified: str | None
    expires_at: float
    freshness_lifetime: float
    must_revalidate: bool


@dataclass
class _CIMDCachePolicy:
    """Normalized cache directives parsed from HTTP response headers."""

    etag: str | None
    last_modified: str | None
    expires_at: float
    freshness_lifetime: float
    no_store: bool
    must_revalidate: bool


class CIMDFetcher:
    """Fetch and validate CIMD documents with SSRF protection.

    Delegates HTTP fetching to ssrf_safe_fetch_response, which provides DNS
    pinning, IP validation, size limits, and timeout enforcement. Documents are
    cached using HTTP caching semantics (Cache-Control/ETag/Last-Modified), with
    a TTL fallback when response headers do not define caching behavior.
    """

    # Maximum response size (bytes)
    MAX_RESPONSE_SIZE = 5120  # 5KB
    # Default cache TTL (seconds)
    DEFAULT_CACHE_TTL_SECONDS = 3600

    def __init__(
        self,
        timeout: float = 10.0,
    ):
        """Initialize the CIMD fetcher.

        Args:
            timeout: HTTP request timeout in seconds (default 10.0)
        """
        self.timeout = timeout
        self._cache: dict[str, _CIMDCacheEntry] = {}

    def _parse_cache_policy(
        self, headers: Mapping[str, str], now: float
    ) -> _CIMDCachePolicy:
        """Parse HTTP cache headers and derive cache behavior."""
        normalized = {k.lower(): v for k, v in headers.items()}
        cache_control = normalized.get("cache-control", "")
        directives = {
            part.strip().lower() for part in cache_control.split(",") if part.strip()
        }

        no_store = "no-store" in directives
        must_revalidate = "no-cache" in directives
        max_age: int | None = None

        for directive in directives:
            if directive.startswith("max-age="):
                value = directive.removeprefix("max-age=").strip()
                try:
                    max_age = max(0, int(value))
                except ValueError:
                    logger.debug(
                        "Ignoring invalid Cache-Control max-age value: %s", value
                    )
                break

        expires_at: float | None = None
        if max_age is not None:
            expires_at = now + max_age
        elif "expires" in normalized:
            try:
                dt = parsedate_to_datetime(normalized["expires"])
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                expires_at = dt.timestamp()
            except (TypeError, ValueError):
                logger.debug(
                    "Ignoring invalid Expires header on CIMD response: %s",
                    normalized["expires"],
                )

        if expires_at is None:
            expires_at = now + self.DEFAULT_CACHE_TTL_SECONDS
        freshness_lifetime = max(0.0, expires_at - now)

        return _CIMDCachePolicy(
            etag=normalized.get("etag"),
            last_modified=normalized.get("last-modified"),
            expires_at=expires_at,
            freshness_lifetime=freshness_lifetime,
            no_store=no_store,
            must_revalidate=must_revalidate,
        )

    def _has_freshness_headers(self, headers: Mapping[str, str]) -> bool:
        """Return True when response includes cache freshness directives."""
        normalized = {k.lower() for k in headers}
        return "cache-control" in normalized or "expires" in normalized

    def is_cimd_client_id(self, client_id: str) -> bool:
        """Check if a client_id looks like a CIMD URL.

        CIMD URLs must be HTTPS with a host and non-root path.
        """
        if not client_id:
            return False
        try:
            parsed = urlparse(client_id)
            return (
                parsed.scheme == "https"
                and bool(parsed.netloc)
                and parsed.path not in ("", "/")
            )
        except (ValueError, AttributeError):
            return False

    async def fetch(self, client_id_url: str) -> CIMDDocument:
        """Fetch and validate a CIMD document with SSRF protection.

        Uses ssrf_safe_fetch_response for the HTTP layer, which provides:
        - HTTPS only, DNS resolution with IP validation
        - DNS pinning (connects to validated IP directly)
        - Blocks private/loopback/link-local/multicast IPs
        - Response size limit and timeout enforcement
        - Redirects disabled

        Args:
            client_id_url: The URL to fetch (also the expected client_id)

        Returns:
            Validated CIMDDocument

        Raises:
            CIMDValidationError: If document is invalid or URL blocked
            CIMDFetchError: If document cannot be fetched
        """
        cached = self._cache.get(client_id_url)
        now = time.time()
        request_headers: dict[str, str] | None = None
        allowed_status_codes = {200}

        if cached is not None:
            if not cached.must_revalidate and now < cached.expires_at:
                return cached.doc

            request_headers = {}
            if cached.etag:
                request_headers["If-None-Match"] = cached.etag
            if cached.last_modified:
                request_headers["If-Modified-Since"] = cached.last_modified
            if request_headers:
                allowed_status_codes = {200, 304}

        try:
            response = await ssrf_safe_fetch_response(
                client_id_url,
                require_path=True,
                max_size=self.MAX_RESPONSE_SIZE,
                timeout=self.timeout,
                overall_timeout=30.0,
                request_headers=request_headers,
                allowed_status_codes=allowed_status_codes,
            )
        except SSRFError as e:
            raise CIMDValidationError(str(e)) from e
        except SSRFFetchError as e:
            raise CIMDFetchError(str(e)) from e

        if response.status_code == 304:
            if cached is None:
                raise CIMDFetchError(
                    "CIMD server returned 304 Not Modified without cached document"
                )

            now = time.time()
            if self._has_freshness_headers(response.headers):
                policy = self._parse_cache_policy(response.headers, now)
            else:
                # RFC allows 304 to omit unchanged headers. Preserve existing
                # cache policy rather than resetting to fallback defaults.
                policy = _CIMDCachePolicy(
                    etag=None,
                    last_modified=None,
                    expires_at=now + cached.freshness_lifetime,
                    freshness_lifetime=cached.freshness_lifetime,
                    no_store=False,
                    must_revalidate=cached.must_revalidate,
                )

            if not policy.no_store:
                self._cache[client_id_url] = _CIMDCacheEntry(
                    doc=cached.doc,
                    etag=policy.etag or cached.etag,
                    last_modified=policy.last_modified or cached.last_modified,
                    expires_at=policy.expires_at,
                    freshness_lifetime=policy.freshness_lifetime,
                    must_revalidate=policy.must_revalidate,
                )
            else:
                self._cache.pop(client_id_url, None)
            return cached.doc

        now = time.time()
        policy = self._parse_cache_policy(response.headers, now)

        try:
            data = json.loads(response.content)
        except json.JSONDecodeError as e:
            raise CIMDValidationError(f"CIMD document is not valid JSON: {e}") from e

        try:
            doc = CIMDDocument.model_validate(data)
        except Exception as e:
            raise CIMDValidationError(f"Invalid CIMD document: {e}") from e

        if str(doc.client_id).rstrip("/") != client_id_url.rstrip("/"):
            raise CIMDValidationError(
                f"CIMD client_id mismatch: document says '{doc.client_id}' "
                f"but was fetched from '{client_id_url}'"
            )

        # Validate jwks_uri if present (SSRF check for JWKS endpoint)
        if doc.jwks_uri:
            jwks_uri_str = str(doc.jwks_uri)
            try:
                await validate_url(jwks_uri_str)
            except SSRFError as e:
                raise CIMDValidationError(
                    f"CIMD jwks_uri failed SSRF validation: {e}"
                ) from e

        logger.info(
            "CIMD document fetched and validated: %s (client_name=%s)",
            client_id_url,
            doc.client_name,
        )

        if not policy.no_store:
            self._cache[client_id_url] = _CIMDCacheEntry(
                doc=doc,
                etag=policy.etag,
                last_modified=policy.last_modified,
                expires_at=policy.expires_at,
                freshness_lifetime=policy.freshness_lifetime,
                must_revalidate=policy.must_revalidate,
            )
        else:
            self._cache.pop(client_id_url, None)

        return doc

    def validate_redirect_uri(self, doc: CIMDDocument, redirect_uri: str) -> bool:
        """Validate that a redirect_uri is allowed by the CIMD document.

        Uses component-level matching (scheme, host, port, path) which correctly
        handles RFC 8252 §7.3 loopback port flexibility and wildcard patterns.

        Args:
            doc: The CIMD document
            redirect_uri: The redirect URI to validate

        Returns:
            True if valid, False otherwise
        """
        if not doc.redirect_uris:
            # No redirect_uris specified - reject all
            return False

        # Normalize for comparison
        redirect_uri = redirect_uri.rstrip("/")

        for allowed in doc.redirect_uris:
            allowed_str = allowed.rstrip("/")
            if matches_allowed_pattern(redirect_uri, allowed_str):
                return True

        return False


class CIMDAssertionValidator:
    """Validates JWT assertions for private_key_jwt CIMD clients.

    Implements RFC 7523 (JSON Web Token (JWT) Profile for OAuth 2.0 Client
    Authentication and Authorization Grants) for CIMD client authentication.

    JTI replay protection uses TTL-based caching to ensure proper security:
    - JTIs are cached with expiration matching the JWT's exp claim
    - Expired JTIs are automatically cleaned up
    - Maximum assertion lifetime is enforced (5 minutes)
    """

    # Maximum allowed assertion lifetime in seconds (RFC 7523 recommends short-lived)
    MAX_ASSERTION_LIFETIME = 300  # 5 minutes

    def __init__(self):
        # JTI cache: maps jti -> expiration timestamp
        self._jti_cache: dict[str, float] = {}
        self._jti_cache_max_size = 10000
        self._last_cleanup = time.monotonic()
        self._cleanup_interval = 60  # Cleanup every 60 seconds
        # Cache JWTVerifier per jwks_uri so JWKS keys are not re-fetched
        # on every token exchange
        self._verifier_cache: dict[str, JWTVerifier] = {}
        self._verifier_cache_max_size = 100
        self.logger = get_logger(__name__)

    def _cleanup_expired_jtis(self) -> None:
        """Remove expired JTIs from cache."""
        pass

    def _maybe_cleanup(self) -> None:
        """Periodically cleanup expired JTIs to prevent unbounded growth."""
        pass

    async def validate_assertion(
        self,
        assertion: str,
        client_id: str,
        token_endpoint: str,
        cimd_doc: CIMDDocument,
    ) -> bool:
        """Validate JWT assertion from client.

        Args:
            assertion: The JWT assertion string
            client_id: Expected client_id (must match iss and sub claims)
            token_endpoint: Token endpoint URL (must match aud claim)
            cimd_doc: CIMD document containing JWKS for key verification

        Returns:
            True if valid

        Raises:
            ValueError: If validation fails
        """
        pass

    def _extract_public_key_from_jwks(self, token: str, jwks: dict) -> str:
        """Extract public key from inline JWKS.

        Args:
            token: JWT token to extract kid from
            jwks: JWKS document containing keys

        Returns:
            PEM-encoded public key

        Raises:
            ValueError: If key cannot be found or extracted
        """
        pass


class CIMDClientManager:
    """Manages all CIMD client operations for OAuth proxy.

    This class encapsulates:
    - CIMD client detection
    - Document fetching and validation
    - Synthetic OAuth client creation
    - Private key JWT assertion validation

    This allows the OAuth proxy to delegate all CIMD-specific logic to a
    single, focused manager class.
    """

    def __init__(
        self,
        enable_cimd: bool = True,
        default_scope: str = "",
        allowed_redirect_uri_patterns: list[str] | None = None,
    ):
        """Initialize CIMD client manager.

        Args:
            enable_cimd: Whether CIMD support is enabled
            default_scope: Default scope for CIMD clients if not specified in document
            allowed_redirect_uri_patterns: Allowed redirect URI patterns (proxy's config)
        """
        self.enabled = enable_cimd
        self.default_scope = default_scope
        self.allowed_redirect_uri_patterns = allowed_redirect_uri_patterns

        self._fetcher = CIMDFetcher()
        self._assertion_validator = CIMDAssertionValidator()
        self.logger = get_logger(__name__)

    def is_cimd_client_id(self, client_id: str) -> bool:
        """Check if client_id is a CIMD URL.

        Args:
            client_id: Client ID to check

        Returns:
            True if client_id is an HTTPS URL (CIMD format)
        """
        return self.enabled and self._fetcher.is_cimd_client_id(client_id)

    async def get_client(self, client_id_url: str):
        """Fetch CIMD document and create synthetic OAuth client.

        Args:
            client_id_url: HTTPS URL pointing to CIMD document

        Returns:
            OAuthProxyClient with CIMD document attached, or None if fetch fails

        Note:
            Return type is left untyped to avoid circular import with oauth_proxy.
            Returns OAuthProxyClient instance or None.
        """
        pass

    async def validate_private_key_jwt(
        self,
        assertion: str,
        client,  # OAuthProxyClient, untyped to avoid circular import
        token_endpoint: str,
    ) -> bool:
        """Validate JWT assertion for private_key_jwt auth.

        Args:
            assertion: JWT assertion string from client
            client: OAuth proxy client (must have cimd_document)
            token_endpoint: Token endpoint URL for aud validation

        Returns:
            True if assertion is valid

        Raises:
            ValueError: If client doesn't have CIMD document or validation fails
        """
        pass
