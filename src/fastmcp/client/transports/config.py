import contextlib
import datetime
from collections.abc import AsyncIterator
from typing import Any

from mcp import ClientSession
from typing_extensions import Unpack

from fastmcp.client.transports.base import ClientTransport, SessionKwargs
from fastmcp.client.transports.memory import FastMCPTransport
from fastmcp.mcp_config import (
    MCPConfig,
    MCPServerTypes,
    RemoteMCPServer,
    StdioMCPServer,
    TransformingRemoteMCPServer,
    TransformingStdioMCPServer,
)
from fastmcp.server.server import FastMCP, create_proxy
from fastmcp.utilities.logging import get_logger

logger = get_logger(__name__)


class MCPConfigTransport(ClientTransport):
    """Transport for connecting to one or more MCP servers defined in an MCPConfig.

    This transport provides a unified interface to multiple MCP servers defined in an MCPConfig
    object or dictionary matching the MCPConfig schema. It supports two key scenarios:

    1. If the MCPConfig contains exactly one server, it creates a direct transport to that server.
    2. If the MCPConfig contains multiple servers, it creates a composite client by mounting
       all servers on a single FastMCP instance, with each server's name, by default, used as its mounting prefix.

    In the multiserver case, tools are accessible with the prefix pattern `{server_name}_{tool_name}`
    and resources with the pattern `protocol://{server_name}/path/to/resource`.

    This is particularly useful for creating clients that need to interact with multiple specialized
    MCP servers through a single interface, simplifying client code.

    Examples:
        ```python
        from fastmcp import Client

        # Create a config with multiple servers
        config = {
            "mcpServers": {
                "weather": {
                    "url": "https://weather-api.example.com/mcp",
                    "transport": "http"
                },
                "calendar": {
                    "url": "https://calendar-api.example.com/mcp",
                    "transport": "http"
                }
            }
        }

        # Create a client with the config
        client = Client(config)

        async with client:
            # Access tools with prefixes
            weather = await client.call_tool("weather_get_forecast", {"city": "London"})
            events = await client.call_tool("calendar_list_events", {"date": "2023-06-01"})

            # Access resources with prefixed URIs
            icons = await client.read_resource("weather://weather/icons/sunny")
        ```
    """

    def __init__(self, config: MCPConfig | dict, name_as_prefix: bool = True):
        if isinstance(config, dict):
            config = MCPConfig.from_dict(config)
        self.config = config
        self.name_as_prefix = name_as_prefix
        self._transports: list[ClientTransport] = []

        if not self.config.mcpServers:
            raise ValueError("No MCP servers defined in the config")

        # For single server, create transport eagerly so it can be inspected
        if len(self.config.mcpServers) == 1:
            self.transport = next(iter(self.config.mcpServers.values())).to_transport()
            self._transports.append(self.transport)

    @contextlib.asynccontextmanager
    async def connect_session(
        self, **session_kwargs: Unpack[SessionKwargs]
    ) -> AsyncIterator[ClientSession]:
        # Single server - delegate directly to pre-created transport
        pass

    async def _create_proxy(
        self,
        name: str,
        config: MCPServerTypes,
        timeout: datetime.timedelta | None,
        stack: contextlib.AsyncExitStack,
    ) -> tuple[ClientTransport, Any, FastMCP[Any]]:
        """Create underlying transport, proxy client, and proxy server for a single backend.

        The ProxyClient is connected via the AsyncExitStack *before* being
        passed to create_proxy so the factory sees it as connected and reuses
        the same session for all tool calls (instead of creating fresh copies).

        Returns a tuple of (transport, proxy_client, proxy_server).
        """
        pass

    async def close(self):
        for transport in self._transports:
            await transport.close()

    def __repr__(self) -> str:
        return f"<MCPConfigTransport(config='{self.config}')>"
