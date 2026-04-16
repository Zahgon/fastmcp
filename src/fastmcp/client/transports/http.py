"""Streamable HTTP transport for FastMCP Client."""

from __future__ import annotations

import contextlib
import datetime
import ssl
from collections.abc import AsyncIterator, Callable
from typing import Any, Literal, cast

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import McpHttpClientFactory, create_mcp_http_client
from pydantic import AnyUrl
from typing_extensions import Unpack

import fastmcp
from fastmcp.client.auth.bearer import BearerAuth
from fastmcp.client.auth.oauth import OAuth
from fastmcp.client.transports.base import ClientTransport, SessionKwargs
from fastmcp.exceptions import FastMCPDeprecationWarning
from fastmcp.server.dependencies import get_http_headers
from fastmcp.utilities.timeout import normalize_timeout_to_timedelta


class StreamableHttpTransport(ClientTransport):
    """Transport implementation that connects to an MCP server via Streamable HTTP Requests."""

    def __init__(
        self,
        url: str | AnyUrl,
        headers: dict[str, str] | None = None,
        auth: httpx.Auth | Literal["oauth"] | str | None = None,
        sse_read_timeout: datetime.timedelta | float | int | None = None,
        httpx_client_factory: McpHttpClientFactory | None = None,
        verify: ssl.SSLContext | bool | str | None = None,
    ):
        """Initialize a Streamable HTTP transport.

        Args:
            url: The MCP server endpoint URL.
            headers: Optional headers to include in requests.
            auth: Authentication method - httpx.Auth, "oauth" for OAuth flow,
                or a bearer token string.
            sse_read_timeout: Deprecated. Use read_timeout_seconds in session_kwargs.
            httpx_client_factory: Optional factory for creating httpx.AsyncClient.
                If provided, must accept keyword arguments: headers, auth,
                follow_redirects, and optionally timeout. Using **kwargs is
                recommended to ensure forward compatibility.
            verify: SSL certificate verification. Accepts False to disable
                verification, a path to a CA bundle, or an ssl.SSLContext
                for full control. None (default) uses httpx defaults (verification
                enabled). Ignored when httpx_client_factory is provided.
        """
        if isinstance(url, AnyUrl):
            url = str(url)
        if not isinstance(url, str) or not url.startswith("http"):
            raise ValueError("Invalid HTTP/S URL provided for Streamable HTTP.")

        # Don't modify the URL path - respect the exact URL provided by the user
        # Some servers are strict about trailing slashes (e.g., PayPal MCP)

        self.url: str = url
        self.headers = headers or {}
        self.httpx_client_factory = httpx_client_factory
        self.verify: ssl.SSLContext | bool | str | None = verify

        if httpx_client_factory is not None and verify is not None:
            import warnings

            warnings.warn(
                "Both 'httpx_client_factory' and 'verify' were provided. "
                "The 'verify' parameter will be ignored because "
                "'httpx_client_factory' takes precedence. Configure SSL "
                "verification directly in your httpx_client_factory instead.",
                UserWarning,
                stacklevel=2,
            )

        self._set_auth(auth)

        if sse_read_timeout is not None:
            if fastmcp.settings.deprecation_warnings:
                import warnings

                warnings.warn(
                    "The `sse_read_timeout` parameter is deprecated and no longer used. "
                    "The new streamable_http_client API does not support this parameter. "
                    "Use `read_timeout_seconds` in session_kwargs or configure timeout on "
                    "the httpx client via `httpx_client_factory` instead.",
                    FastMCPDeprecationWarning,
                    stacklevel=2,
                )
        self.sse_read_timeout = normalize_timeout_to_timedelta(sse_read_timeout)

        self.forward_incoming_headers: bool = False

        self._get_session_id_cb: Callable[[], str | None] | None = None

    def _set_auth(self, auth: httpx.Auth | Literal["oauth"] | str | None):
        pass

    def _make_verify_factory(self) -> McpHttpClientFactory | None:
        pass

    @contextlib.asynccontextmanager
    async def connect_session(
        self, **session_kwargs: Unpack[SessionKwargs]
    ) -> AsyncIterator[ClientSession]:
        # When used in a proxy, forward the inbound request's authorization
        # header to the upstream server. This is off by default so that a
        # plain Client used inside a server tool handler doesn't accidentally
        # leak the caller's credentials to an unrelated remote server.
        pass

    def get_session_id(self) -> str | None:
        if self._get_session_id_cb:
            try:
                return self._get_session_id_cb()
            except Exception:
                return None
        return None

    async def close(self):
        # Reset the session id callback
        self._get_session_id_cb = None

    def __repr__(self) -> str:
        return f"<StreamableHttpTransport(url='{self.url}')>"
