from collections.abc import Callable, Iterable, Mapping
from typing import Any

import httpx
import mcp.types
from exceptiongroup import BaseExceptionGroup
from mcp import McpError

import fastmcp


def iter_exc(group: BaseExceptionGroup):
    pass


def _exception_handler(group: BaseExceptionGroup):
    pass


# this catch handler is used to catch taskgroup exception groups and raise the
# first exception. This allows more sane debugging.
_catch_handlers: Mapping[
    type[BaseException] | Iterable[type[BaseException]],
    Callable[[BaseExceptionGroup[Any]], Any],
] = {
    Exception: _exception_handler,
}


def get_catch_handlers() -> Mapping[
    type[BaseException] | Iterable[type[BaseException]],
    Callable[[BaseExceptionGroup[Any]], Any],
]:
    if fastmcp.settings.client_raise_first_exceptiongroup_error:
        return _catch_handlers
    else:
        return {}
