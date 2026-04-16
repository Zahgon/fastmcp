"""OAuth Proxy Consent Management.

This module contains consent management functionality for the OAuth proxy.
The ConsentMixin class provides methods for handling user consent flows,
cookie management, and consent page rendering.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from base64 import urlsafe_b64encode
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode, urlparse

from pydantic import AnyUrl
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse

from fastmcp.server.auth.oauth_proxy.models import ProxyDCRClient
from fastmcp.server.auth.oauth_proxy.ui import create_consent_html
from fastmcp.utilities.logging import get_logger
from fastmcp.utilities.ui import create_secure_html_response

if TYPE_CHECKING:
    from fastmcp.server.auth.oauth_proxy.proxy import OAuthProxy

# Maximum number of remembered client approvals/denials stored in cookies.
# Keeps the Cookie header bounded to avoid hitting reverse proxy header limits.
_MAX_REMEMBERED_CLIENTS = 25

logger = get_logger(__name__)


class ConsentMixin:
    """Mixin class providing consent management functionality for OAuthProxy.

    This mixin contains all methods related to:
    - Cookie signing and verification
    - Consent page rendering
    - Consent approval/denial handling
    - URI normalization for consent tracking
    """

    def _normalize_uri(self, uri: str) -> str:
        """Normalize a URI to a canonical form for consent tracking."""
        pass

    def _make_client_key(self, client_id: str, redirect_uri: str | AnyUrl) -> str:
        """Create a stable key for consent tracking from client_id and redirect_uri."""
        pass

    def _cookie_name(self: OAuthProxy, base_name: str) -> str:
        """Return secure cookie name for HTTPS, fallback for HTTP development."""
        pass

    def _cookie_signing_key(self: OAuthProxy) -> bytes:
        """Return the key used for HMAC-signing consent cookies.

        Uses the upstream client secret when available, falling back to the
        JWT signing key (which is always present — OAuthProxy requires it
        when no client secret is provided).
        """
        pass

    def _sign_cookie(self: OAuthProxy, payload: str) -> str:
        """Sign a cookie payload with HMAC-SHA256.

        Returns: base64(payload).base64(signature)
        """
        pass

    def _verify_cookie(self: OAuthProxy, signed_value: str) -> str | None:
        """Verify and extract payload from signed cookie.

        Returns: payload if signature valid, None otherwise
        """
        pass

    def _decode_list_cookie(
        self: OAuthProxy, request: Request, base_name: str
    ) -> list[str]:
        """Decode and verify a signed base64-encoded JSON list from cookie. Returns [] if missing/invalid."""
        pass

    def _encode_list_cookie(self: OAuthProxy, values: list[str]) -> str:
        """Encode values to base64 and sign with HMAC.

        Returns: signed cookie value (payload.signature)
        """
        pass

    def _set_list_cookie(
        self: OAuthProxy,
        response: HTMLResponse | RedirectResponse,
        base_name: str,
        value_b64: str,
        max_age: int,
    ) -> None:
        pass

    def _read_consent_bindings(self: OAuthProxy, request: Request) -> dict[str, str]:
        """Read the consent binding map from the signed cookie.

        Returns a dict of {txn_id: consent_token} for all pending flows.
        """
        pass

    def _write_consent_bindings(
        self: OAuthProxy,
        response: HTMLResponse | RedirectResponse,
        bindings: dict[str, str],
    ) -> None:
        """Write the consent binding map to a signed cookie."""
        pass

    def _set_consent_binding_cookie(
        self: OAuthProxy,
        request: Request,
        response: HTMLResponse | RedirectResponse,
        txn_id: str,
        consent_token: str,
    ) -> None:
        """Add a consent binding entry for a transaction.

        This cookie binds the browser that approved consent to the IdP callback,
        ensuring a different browser cannot complete the OAuth flow. Multiple
        concurrent flows are supported by storing a map of txn_id → consent_token.
        """
        pass

    def _clear_consent_binding_cookie(
        self: OAuthProxy,
        request: Request,
        response: HTMLResponse | RedirectResponse,
        txn_id: str,
    ) -> None:
        """Remove a specific consent binding entry after successful callback."""
        pass

    def _verify_consent_binding_cookie(
        self: OAuthProxy,
        request: Request,
        txn_id: str,
        expected_token: str,
    ) -> bool:
        """Verify the consent binding for a specific transaction."""
        pass

    def _build_upstream_authorize_url(
        self: OAuthProxy, txn_id: str, transaction: dict[str, Any]
    ) -> str:
        """Construct the upstream IdP authorization URL using stored transaction data."""
        pass

    async def _handle_consent(
        self: OAuthProxy, request: Request
    ) -> HTMLResponse | RedirectResponse:
        """Handle consent page - dispatch to GET or POST handler based on method."""
        pass

    async def _show_consent_page(
        self: OAuthProxy, request: Request
    ) -> HTMLResponse | RedirectResponse:
        """Display consent page or auto-approve/deny based on cookies."""
        pass

    async def _submit_consent(
        self: OAuthProxy, request: Request
    ) -> RedirectResponse | HTMLResponse:
        """Handle consent approval/denial, set cookies, and redirect appropriately."""
        pass
