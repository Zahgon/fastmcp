"""FormInput — a Provider that collects structured input from the user.

Define a Pydantic model for the data you need, and ``FormInput``
generates a form UI. The user fills it out, the submission is
validated, and an optional callback processes the result.

Requires ``fastmcp[apps]`` (prefab-ui).

Usage::

    from pydantic import BaseModel
    from fastmcp import FastMCP
    from fastmcp.apps.form import FormInput

    class ShippingAddress(BaseModel):
        street: str
        city: str
        state: str
        zip_code: str

    mcp = FastMCP("My Server")
    mcp.add_provider(FormInput(model=ShippingAddress))
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from packaging.version import InvalidVersion, Version

try:
    import prefab_ui
    from prefab_ui.actions import SetState
    from prefab_ui.actions.mcp import CallTool, SendMessage
    from prefab_ui.app import PrefabApp
    from prefab_ui.components import (
        H3,
        Card,
        CardContent,
        CardFooter,
        CardHeader,
        Column,
        Form,
        Muted,
    )
    from prefab_ui.components.control_flow import If
    from prefab_ui.rx import RESULT, STATE
except ImportError as _exc:
    raise ImportError(
        "FormInput requires prefab-ui. Install with: pip install 'fastmcp[apps]'"
    ) from _exc

# `defaults` kwarg on Form.from_model was added in prefab-ui 0.19.1. Gate on
# version so that older prefab-ui keeps working — `default` silently no-ops.
try:
    _FORM_SUPPORTS_DEFAULTS = Version(prefab_ui.__version__) >= Version("0.19.1")
except InvalidVersion:
    _FORM_SUPPORTS_DEFAULTS = False

import pydantic

from fastmcp.apps.app import FastMCPApp


def _backfill_boolean_defaults(
    model: type[pydantic.BaseModel],
    data: dict[str, Any],
) -> dict[str, Any]:
    """Fill in missing boolean fields with their model defaults.

    HTML checkboxes omit the field entirely when unchecked, so the
    submitted data dict won't contain a key for ``False`` booleans.
    This backfills those missing keys so Pydantic validation succeeds.
    """
    for name, field_info in model.model_fields.items():
        if name in data:
            continue
        if field_info.annotation is bool:
            if field_info.default is not pydantic.fields.PydanticUndefined:
                data[name] = field_info.default
            else:
                data[name] = False
    return data


class FormInput(FastMCPApp):
    """A Provider that collects structured input via a Pydantic model.

    Define a model for the data you need, and ``FormInput`` generates
    a form from it using ``Form.from_model()``. Field types, labels,
    descriptions, and validation are all derived from the model.

    Optionally provide an ``on_submit`` callback to process the
    validated data. The callback receives a model instance and returns
    a string that goes back to the LLM. Without a callback, the
    validated JSON is sent directly.

    Example::

        from pydantic import BaseModel
        from fastmcp import FastMCP
        from fastmcp.apps.form import FormInput

        class Contact(BaseModel):
            name: str
            email: str

        mcp = FastMCP("My Server")
        mcp.add_provider(FormInput(model=Contact))

    With a callback::

        def save_contact(contact: Contact) -> str:
            db.insert(contact.model_dump())
            return f"Saved {contact.name}"

        mcp.add_provider(FormInput(model=Contact, on_submit=save_contact))
    """

    def __init__(
        self,
        model: type[pydantic.BaseModel],
        *,
        name: str | None = None,
        title: str | None = None,
        submit_text: str = "Submit",
        tool_name: str | None = None,
        on_submit: Callable[..., str] | None = None,
        send_message: bool = False,
    ) -> None:
        app_name = name or model.__name__
        super().__init__(app_name)
        self._model = model
        self._title = title or model.__name__
        self._submit_text = submit_text
        self._tool_name = tool_name or f"collect_{model.__name__.lower()}"
        self._on_submit = on_submit
        self._send_message = send_message
        self._register_tools()

    def __repr__(self) -> str:
        return f"FormInput({self._model.__name__!r})"

    def _register_tools(self) -> None:
        pass
