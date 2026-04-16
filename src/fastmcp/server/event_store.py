"""EventStore implementation backed by AsyncKeyValue.

This module provides an EventStore implementation that enables SSE polling/resumability
for Streamable HTTP transports. Events are stored using the key_value package's
AsyncKeyValue protocol, allowing users to configure any compatible backend
(in-memory, Redis, etc.) following the same pattern as ResponseCachingMiddleware.
"""

from __future__ import annotations

from uuid import uuid4

from key_value.aio.adapters.pydantic import PydanticAdapter
from key_value.aio.protocols import AsyncKeyValue
from key_value.aio.stores.memory import MemoryStore
from mcp.server.streamable_http import EventCallback, EventId, EventMessage, StreamId
from mcp.server.streamable_http import EventStore as SDKEventStore
from mcp.types import JSONRPCMessage

from fastmcp.utilities.logging import get_logger
from fastmcp.utilities.types import FastMCPBaseModel

logger = get_logger(__name__)


class EventEntry(FastMCPBaseModel):
    """Stored event entry."""

    event_id: str
    stream_id: str
    message: dict | None  # JSONRPCMessage serialized to dict


class StreamEventList(FastMCPBaseModel):
    """List of event IDs for a stream."""

    event_ids: list[str]


class EventStore(SDKEventStore):
    """EventStore implementation backed by AsyncKeyValue.

    Enables SSE polling/resumability by storing events that can be replayed
    when clients reconnect. Works with any AsyncKeyValue backend (memory, Redis, etc.)
    following the same pattern as ResponseCachingMiddleware and OAuthProxy.

    Example:
        ```python
        from fastmcp import FastMCP
        from fastmcp.server.event_store import EventStore

        # Default in-memory storage
        event_store = EventStore()

        # Or with a custom backend
        from key_value.aio.stores.redis import RedisStore
        redis_backend = RedisStore(url="redis://localhost")
        event_store = EventStore(storage=redis_backend)

        mcp = FastMCP("MyServer")
        app = mcp.http_app(event_store=event_store, retry_interval=2000)
        ```

    Args:
        storage: AsyncKeyValue backend. Defaults to MemoryStore.
        max_events_per_stream: Maximum events to retain per stream. Default 100.
        ttl: Event TTL in seconds. Default 3600 (1 hour). Set to None for no expiration.
    """

    def __init__(
        self,
        storage: AsyncKeyValue | None = None,
        max_events_per_stream: int = 100,
        ttl: int | None = 3600,
    ):
        self._storage: AsyncKeyValue = storage or MemoryStore()
        self._max_events_per_stream = max_events_per_stream
        self._ttl = ttl

        # PydanticAdapter for type-safe storage (following OAuth proxy pattern)
        self._event_store: PydanticAdapter[EventEntry] = PydanticAdapter[EventEntry](
            key_value=self._storage,
            pydantic_model=EventEntry,
            default_collection="fastmcp_events",
        )
        self._stream_store: PydanticAdapter[StreamEventList] = PydanticAdapter[
            StreamEventList
        ](
            key_value=self._storage,
            pydantic_model=StreamEventList,
            default_collection="fastmcp_streams",
        )

    async def store_event(
        self, stream_id: StreamId, message: JSONRPCMessage | None
    ) -> EventId:
        """Store an event and return its ID.

        Args:
            stream_id: ID of the stream the event belongs to
            message: The JSON-RPC message to store, or None for priming events

        Returns:
            The generated event ID for the stored event
        """
        pass

    async def replay_events_after(
        self,
        last_event_id: EventId,
        send_callback: EventCallback,
    ) -> StreamId | None:
        """Replay events that occurred after the specified event ID.

        Args:
            last_event_id: The ID of the last event the client received
            send_callback: A callback function to send events to the client

        Returns:
            The stream ID of the replayed events, or None if the event ID was not found
        """
        pass
