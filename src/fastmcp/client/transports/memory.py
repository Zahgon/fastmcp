import contextlib
from collections.abc import AsyncIterator

import anyio
from mcp import ClientSession
from mcp.server.fastmcp import FastMCP as FastMCP1Server
from mcp.shared.memory import create_client_server_memory_streams
from typing_extensions import Unpack

from fastmcp.client.transports.base import ClientTransport, SessionKwargs
from fastmcp.server.server import FastMCP


class FastMCPTransport(ClientTransport):
    """In-memory transport for FastMCP servers.

    This transport connects directly to a FastMCP server instance in the same
    Python process. It works with both FastMCP 2.x servers and FastMCP 1.0
    servers from the low-level MCP SDK. This is particularly useful for unit
    tests or scenarios where client and server run in the same runtime.
    """

    def __init__(self, mcp: FastMCP | FastMCP1Server, raise_exceptions: bool = False):
        """Initialize a FastMCPTransport from a FastMCP server instance."""

        # Accept both FastMCP 2.x and FastMCP 1.0 servers. Both expose a
        # ``_mcp_server`` attribute pointing to the underlying MCP server
        # implementation, so we can treat them identically.
        self.server = mcp
        self.raise_exceptions = raise_exceptions

    @contextlib.asynccontextmanager
    async def connect_session(
        self, **session_kwargs: Unpack[SessionKwargs]
    ) -> AsyncIterator[ClientSession]:
        pass

    def __repr__(self) -> str:
        return f"<FastMCPTransport(server='{self.server.name}')>"


@contextlib.asynccontextmanager
async def _enter_server_lifespan(
    server: FastMCP | FastMCP1Server,
) -> AsyncIterator[None]:
    """Enters the server's lifespan context for FastMCP servers and does nothing for FastMCP 1 servers."""
    pass
