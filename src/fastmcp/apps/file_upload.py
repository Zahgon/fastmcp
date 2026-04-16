"""FileUpload — a Provider that adds drag-and-drop file upload to any server.

Lets users upload files directly to the server through an interactive UI,
bypassing the LLM context window entirely. The LLM can then read and work
with uploaded files through model-visible tools.

Requires ``fastmcp[apps]`` (prefab-ui).

Usage::

    from fastmcp import FastMCP
    from fastmcp.apps import FileUpload

    mcp = FastMCP("My Server")
    mcp.add_provider(FileUpload())

For custom persistence, override the storage methods::

    class S3Upload(FileUpload):
        def on_store(self, files, ctx):
            # write to S3, return summaries
            ...

        def on_list(self, ctx):
            # list from S3
            ...

        def on_read(self, name, ctx):
            # read from S3
            ...
"""

from __future__ import annotations

try:
    from prefab_ui.actions import SetState, ShowToast
    from prefab_ui.actions.mcp import CallTool
    from prefab_ui.app import PrefabApp
    from prefab_ui.components import (
        H3,
        Badge,
        Button,
        Card,
        CardContent,
        CardFooter,
        CardHeader,
        Column,
        DropZone,
        Muted,
        Row,
        Separator,
        Small,
        Text,
    )
    from prefab_ui.components.control_flow import Else, ForEach, If
    from prefab_ui.rx import ERROR, RESULT, STATE, Rx
except ImportError as _exc:
    raise ImportError(
        "FileUpload requires prefab-ui. Install with: pip install 'fastmcp[apps]'"
    ) from _exc

import base64
from datetime import datetime, timezone
from typing import Any

from fastmcp.apps.app import FastMCPApp
from fastmcp.server.context import Context

_TEXT_EXTENSIONS = frozenset(
    (".csv", ".json", ".txt", ".md", ".py", ".yaml", ".yml", ".toml")
)


def _b64_decoded_size(b64: str) -> int:
    """Return the exact decoded byte-length of a base64 string without decoding it."""
    n = len(b64)
    if n == 0:
        return 0
    padding = b64.count("=", max(0, n - 2))
    return n * 3 // 4 - padding


def _format_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    elif size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    else:
        return f"{size / (1024 * 1024):.1f} MB"


def _make_summary(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": entry["name"],
        "type": entry["type"],
        "size": entry["size"],
        "size_display": _format_size(entry["size"]),
        "uploaded_at": entry["uploaded_at"],
    }


class FileUpload(FastMCPApp):
    """A Provider that adds file upload capabilities to a server.

    Registers a drag-and-drop UI tool, a backend storage tool, and
    model-visible tools for listing and reading uploaded files.

    Files are scoped by MCP session and stored in memory by default.
    Override ``on_store``, ``on_list``, and ``on_read`` for custom
    persistence (filesystem, S3, database, etc.). Each method receives
    the current ``Context``, giving access to session ID, auth tokens,
    and request metadata for partitioning and authorization.

    **Session scoping:** The default storage uses ``ctx.session_id`` to
    isolate files by session. This works with stdio, SSE, and stateful
    HTTP transports. In **stateless HTTP** mode, each request creates a
    new session, so files won't persist across requests. For stateless
    deployments, override the storage methods to partition by a stable
    identifier from the auth context::

        class UserScopedUpload(FileUpload):
            def on_store(self, files, ctx):
                user_id = ctx.access_token["sub"]
                ...

    Example::

        from fastmcp import FastMCP
        from fastmcp.apps.file_upload import FileUpload

        mcp = FastMCP("My Server")
        mcp.add_provider(FileUpload())
    """

    def __init__(
        self,
        name: str = "Files",
        *,
        max_file_size: int = 10 * 1024 * 1024,
        title: str = "File Upload",
        description: str = (
            "Drop files to upload them to the server. "
            "The model can then read and analyze them "
            "without using the context window."
        ),
        drop_label: str = "Drop files here",
    ) -> None:
        super().__init__(name)
        self._max_file_size = max_file_size
        self._title = title
        self._description = description
        self._drop_label = drop_label

        # Default in-memory store, keyed by session_id
        self._store: dict[str, dict[str, dict[str, Any]]] = {}

        self._register_tools()

    def __repr__(self) -> str:
        return f"FileUpload({self.name!r})"

    # ------------------------------------------------------------------
    # Storage interface — override these for custom persistence
    # ------------------------------------------------------------------

    def _get_scope_key(self, ctx: Context) -> str:
        """Return the key used to partition file storage.

        Defaults to ``ctx.session_id``, which is stable for stdio, SSE,
        and stateful HTTP. The default ``on_store``/``on_list``/``on_read``
        implementations call this to partition the in-memory store.

        Override to scope by user, tenant, or any other dimension::

            def _get_scope_key(self, ctx):
                return ctx.access_token["sub"]
        """
        try:
            return ctx.session_id
        except RuntimeError:
            return "__default__"

    def on_store(
        self,
        files: list[dict[str, Any]],
        ctx: Context,
    ) -> list[dict[str, Any]]:
        """Store uploaded files and return summaries.

        Args:
            files: List of file dicts, each with ``name``, ``size``,
                ``type``, and ``data`` (base64-encoded content).
            ctx: The current request context. Use for session ID,
                auth tokens, or any metadata needed for partitioning.

        Override this method for custom persistence. The default
        implementation stores files in memory, scoped by
        ``_get_scope_key(ctx)``.

        Returns:
            List of file summary dicts (``name``, ``type``, ``size``,
            ``size_display``, ``uploaded_at``).
        """
        pass

    def on_list(self, ctx: Context) -> list[dict[str, Any]]:
        """List all stored files.

        Args:
            ctx: The current request context.

        Override this method for custom persistence. The default
        implementation returns files from the current scope.

        Returns:
            List of file summary dicts.
        """
        scope = self._get_scope_key(ctx)
        session_files = self._store.get(scope, {})
        return [_make_summary(e) for e in session_files.values()]

    def on_read(self, name: str, ctx: Context) -> dict[str, Any]:
        """Read a file's contents by name.

        Args:
            name: The filename to read.
            ctx: The current request context.

        Override this method for custom persistence. The default
        implementation reads from the current scope's in-memory store.
        Text files are decoded from base64; binary files return a
        truncated base64 preview.

        Returns:
            Dict with file metadata and ``content`` (text) or
            ``content_base64`` (binary preview).

        Raises:
            ValueError: If the file is not found.
        """
        pass

    # ------------------------------------------------------------------
    # Tool registration
    # ------------------------------------------------------------------

    def _register_tools(self) -> None:
        pass
