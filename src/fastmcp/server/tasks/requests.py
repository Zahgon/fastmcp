"""SEP-1686 task request handlers.

Handles MCP task protocol requests: tasks/get, tasks/result, tasks/list, tasks/cancel.
These handlers query and manage existing tasks (contrast with handlers.py which creates tasks).

This module requires fastmcp[tasks] (pydocket). It is only imported when docket is available.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Literal

import mcp.types
from docket.execution import ExecutionState
from mcp.shared.exceptions import McpError
from mcp.types import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    CancelTaskResult,
    ErrorData,
    GetTaskResult,
    ListTasksResult,
)

import fastmcp.server.context
from fastmcp.exceptions import NotFoundError
from fastmcp.prompts.base import Prompt
from fastmcp.resources.base import Resource
from fastmcp.resources.template import ResourceTemplate
from fastmcp.server.tasks.config import DEFAULT_POLL_INTERVAL_MS, DEFAULT_TTL_MS
from fastmcp.server.tasks.context import get_task_scope
from fastmcp.server.tasks.keys import parse_task_key, task_redis_prefix
from fastmcp.tools.base import Tool
from fastmcp.utilities.versions import VersionSpec

if TYPE_CHECKING:
    from fastmcp.server.server import FastMCP


# Map Docket execution states to MCP task status strings
# Per SEP-1686 final spec (line 381): tasks MUST begin in "working" status
DOCKET_TO_MCP_STATE: dict[ExecutionState, str] = {
    ExecutionState.SCHEDULED: "working",  # Initial state per spec
    ExecutionState.QUEUED: "working",  # Initial state per spec
    ExecutionState.RUNNING: "working",
    ExecutionState.COMPLETED: "completed",
    ExecutionState.FAILED: "failed",
    ExecutionState.CANCELLED: "cancelled",
}


def _parse_key_version(key_suffix: str) -> tuple[str, str | None]:
    """Parse a key suffix into (name_or_uri, version).

    Keys always contain @ as a version delimiter (sentinel pattern):
    - "add@1.0" → ("add", "1.0")  # versioned
    - "add@" → ("add", None)      # unversioned
    - "user@example.com@1.0" → ("user@example.com", "1.0")  # @ in URI

    Uses rsplit to split on the LAST @ which is always the version delimiter.
    Falls back to treating the whole string as the name if @ is not present
    (for backwards compatibility with legacy task keys).
    """
    pass


async def _lookup_task_execution(
    docket: Any,
    task_scope: str | None,
    client_task_id: str,
) -> tuple[Any, str | None, int]:
    """Look up task execution and metadata from Redis.

    Consolidates the common pattern of fetching task metadata from Redis,
    validating it exists, and retrieving the Docket execution.

    Args:
        docket: Docket instance
        task_scope: Authorization scope
        client_task_id: Client-provided task ID

    Returns:
        Tuple of (execution, created_at, poll_interval_ms)

    Raises:
        McpError: If task not found or execution not found
    """
    pass


async def tasks_get_handler(server: FastMCP, params: dict[str, Any]) -> GetTaskResult:
    """Handle MCP 'tasks/get' request (SEP-1686).

    Args:
        server: FastMCP server instance
        params: Request params containing taskId

    Returns:
        GetTaskResult: Task status response with spec-compliant fields
    """
    pass


async def tasks_result_handler(server: FastMCP, params: dict[str, Any]) -> Any:
    """Handle MCP 'tasks/result' request (SEP-1686).

    Converts raw task return values to MCP types based on task type.

    Args:
        server: FastMCP server instance
        params: Request params containing taskId

    Returns:
        MCP result (CallToolResult, GetPromptResult, or ReadResourceResult)
    """
    pass


async def tasks_list_handler(
    server: FastMCP, params: dict[str, Any]
) -> ListTasksResult:
    """Handle MCP 'tasks/list' request (SEP-1686).

    Note: With client-side tracking, this returns minimal info.

    Args:
        server: FastMCP server instance
        params: Request params (cursor, limit)

    Returns:
        ListTasksResult: Response with tasks list and pagination
    """
    pass


async def tasks_cancel_handler(
    server: FastMCP, params: dict[str, Any]
) -> CancelTaskResult:
    """Handle MCP 'tasks/cancel' request (SEP-1686).

    Cancels a running task, transitioning it to cancelled state.

    Args:
        server: FastMCP server instance
        params: Request params containing taskId

    Returns:
        CancelTaskResult: Task status response showing cancelled state
    """
    pass
