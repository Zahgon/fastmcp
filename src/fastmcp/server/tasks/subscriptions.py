"""Task subscription helpers for sending MCP notifications (SEP-1686).

Subscribes to Docket execution state changes and sends notifications/tasks/status
to clients when their tasks change state.

This module requires fastmcp[tasks] (pydocket). It is only imported when docket is available.
"""

from __future__ import annotations

from contextlib import suppress
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from docket.execution import ExecutionState
from mcp.types import TaskStatusNotification, TaskStatusNotificationParams

from fastmcp.server.tasks.config import DEFAULT_TTL_MS
from fastmcp.server.tasks.keys import parse_task_key, task_redis_prefix
from fastmcp.server.tasks.requests import DOCKET_TO_MCP_STATE
from fastmcp.utilities.logging import get_logger

if TYPE_CHECKING:
    from docket import Docket
    from docket.execution import Execution
    from mcp.server.session import ServerSession

logger = get_logger(__name__)


async def subscribe_to_task_updates(
    task_id: str,
    task_key: str,
    session: ServerSession,
    docket: Docket,
    poll_interval_ms: int = 5000,
) -> None:
    """Subscribe to Docket execution events and send MCP notifications.

    Per SEP-1686 lines 436-444, servers MAY send notifications/tasks/status
    when task state changes. This is an optional optimization that reduces
    client polling frequency.

    Args:
        task_id: Client-visible task ID (server-generated UUID)
        task_key: Internal Docket execution key (includes session, type, component)
        session: MCP ServerSession for sending notifications
        docket: Docket instance for subscribing to execution events
        poll_interval_ms: Poll interval in milliseconds to include in notifications
    """
    pass


async def _send_status_notification(
    session: ServerSession,
    task_id: str,
    task_key: str,
    docket: Docket,
    state: ExecutionState,
    poll_interval_ms: int = 5000,
) -> None:
    """Send notifications/tasks/status to client.

    Per SEP-1686 line 454: notification SHOULD NOT include related-task metadata
    (taskId is already in params).

    Args:
        session: MCP ServerSession
        task_id: Client-visible task ID
        task_key: Internal task key (for metadata lookup)
        docket: Docket instance
        state: Docket execution state (enum)
        poll_interval_ms: Poll interval in milliseconds
    """
    pass


async def _send_progress_notification(
    session: ServerSession,
    task_id: str,
    task_key: str,
    docket: Docket,
    execution: Execution,
    poll_interval_ms: int = 5000,
) -> None:
    """Send notifications/tasks/status when progress updates.

    Args:
        session: MCP ServerSession
        task_id: Client-visible task ID
        task_key: Internal task key
        docket: Docket instance
        execution: Execution object with current progress
        poll_interval_ms: Poll interval in milliseconds
    """
    pass
