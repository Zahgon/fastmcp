"""Server-Sent Events (SSE) transport for FastMCP Client."""

from __future__ import annotations

import contextlib
import datetime
import ssl
from collections.abc import AsyncIterator
from typing import Any, Literal, cast

import httpx
from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.shared._httpx_utils import McpHttpClientFactory
from pydantic import AnyUrl
from typing_extensions import Unpack

from fastmcp.client.auth.bearer import BearerAuth
from fastmcp.client.auth.oauth import OAuth
from fastmcp.client.transports.base import ClientTransport, SessionKwargs
from fastmcp.server.dependencies import get_http_headers
from fastmcp.utilities.timeout import normalize_timeout_to_timedelta


class SSETransport(ClientTransport):
    """Transport implementation that connects to an MCP server via Server-Sent Events."""

    def __init__(
        self,
        url: str | AnyUrl,
        headers: dict[str, str] | None = None,
        auth: httpx.Auth | Literal["oauth"] | str | None = None,
        sse_read_timeout: datetime.timedelta | float | int | None = None,
        httpx_client_factory: McpHttpClientFactory | None = None,
        verify: ssl.SSLContext | bool | str | None = None,
    ):
        if isinstance(url, AnyUrl):
            url = str(url)
        if not isinstance(url, str) or not url.startswith("http"):
            raise ValueError("Invalid HTTP/S URL provided for SSE.")

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

        self.forward_incoming_headers: bool = False

        self.sse_read_timeout = normalize_timeout_to_timedelta(sse_read_timeout)

    def _set_auth(self, auth: httpx.Auth | Literal["oauth"] | str | None):
        pass

    def _make_verify_factory(self) -> McpHttpClientFactory | None:
        pass

    @contextlib.asynccontextmanager
    async def connect_session(
        self, **session_kwargs: Unpack[SessionKwargs]
    ) -> AsyncIterator[ClientSession]:
        pass

    def __repr__(self) -> str:
        return f"<SSETransport(url='{self.url}')>"
