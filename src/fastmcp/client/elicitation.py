from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Generic, TypeAlias

import mcp.types
from mcp import ClientSession
from mcp.client.session import ElicitationFnT
from mcp.shared.context import LifespanContextT, RequestContext
from mcp.types import ElicitRequestFormParams, ElicitRequestParams
from mcp.types import ElicitResult as MCPElicitResult
from pydantic_core import to_jsonable_python
from typing_extensions import TypeVar

from fastmcp.utilities.json_schema_type import json_schema_to_type

__all__ = ["ElicitRequestParams", "ElicitResult", "ElicitationHandler"]

T = TypeVar("T", default=Any)


class ElicitResult(MCPElicitResult, Generic[T]):
    content: T | None = None


ElicitationHandler: TypeAlias = Callable[
    [
        str,  # message
        type[T]
        | None,  # a class for creating a structured response (None for URL elicitation)
        ElicitRequestParams,
        RequestContext[ClientSession, LifespanContextT],
    ],
    Awaitable[T | dict[str, Any] | ElicitResult[T | dict[str, Any]]],
]


def create_elicitation_callback(
    elicitation_handler: ElicitationHandler,
) -> ElicitationFnT:
    async def _elicitation_handler(
        context: RequestContext[ClientSession, LifespanContextT],
        params: ElicitRequestParams,
    ) -> MCPElicitResult | mcp.types.ErrorData:
        pass

    return _elicitation_handler
