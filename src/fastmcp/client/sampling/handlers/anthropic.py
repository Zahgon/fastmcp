"""Anthropic sampling handler for FastMCP."""

from collections.abc import Iterator, Sequence
from typing import Any

from mcp.types import (
    AudioContent,
    CreateMessageResult,
    CreateMessageResultWithTools,
    ImageContent,
    ModelPreferences,
    SamplingMessage,
    SamplingMessageContentBlock,
    StopReason,
    TextContent,
    Tool,
    ToolChoice,
    ToolResultContent,
    ToolUseContent,
)
from mcp.types import CreateMessageRequestParams as SamplingParams

try:
    from anthropic import AsyncAnthropic
    from anthropic.types import (
        Base64ImageSourceParam,
        ImageBlockParam,
        Message,
        MessageParam,
        TextBlock,
        TextBlockParam,
        ToolParam,
        ToolResultBlockParam,
        ToolUseBlock,
        ToolUseBlockParam,
    )
    from anthropic.types.model_param import ModelParam
    from anthropic.types.tool_choice_any_param import ToolChoiceAnyParam
    from anthropic.types.tool_choice_auto_param import ToolChoiceAutoParam
    from anthropic.types.tool_choice_param import ToolChoiceParam
except ImportError as e:
    raise ImportError(
        "The `anthropic` package is not installed. "
        "Install it with `pip install fastmcp[anthropic]` or add `anthropic` to your dependencies."
    ) from e

__all__ = ["AnthropicSamplingHandler"]

# Anthropic supports these image MIME types
_ANTHROPIC_IMAGE_MEDIA_TYPES = frozenset(
    {"image/jpeg", "image/png", "image/gif", "image/webp"}
)


def _image_content_to_anthropic_block(content: ImageContent) -> ImageBlockParam:
    """Convert MCP ImageContent to Anthropic ImageBlockParam."""
    if content.mimeType not in _ANTHROPIC_IMAGE_MEDIA_TYPES:
        raise ValueError(
            f"Unsupported image MIME type for Anthropic: {content.mimeType!r}. "
            f"Supported types: {', '.join(sorted(_ANTHROPIC_IMAGE_MEDIA_TYPES))}"
        )
    return ImageBlockParam(
        type="image",
        source=Base64ImageSourceParam(
            type="base64",
            media_type=content.mimeType,  # type: ignore[arg-type]  # ty:ignore[invalid-argument-type]
            data=content.data,
        ),
    )


class AnthropicSamplingHandler:
    """Sampling handler that uses the Anthropic API.

    Example:
        ```python
        from anthropic import AsyncAnthropic
        from fastmcp import FastMCP
        from fastmcp.client.sampling.handlers.anthropic import AnthropicSamplingHandler

        handler = AnthropicSamplingHandler(
            default_model="claude-sonnet-4-5",
            client=AsyncAnthropic(),
        )

        server = FastMCP(sampling_handler=handler)
        ```
    """

    def __init__(
        self, default_model: ModelParam, client: AsyncAnthropic | None = None
    ) -> None:
        self.client: AsyncAnthropic = client or AsyncAnthropic()
        self.default_model: ModelParam = default_model

    async def __call__(
        self,
        messages: list[SamplingMessage],
        params: SamplingParams,
        context: Any,
    ) -> CreateMessageResult | CreateMessageResultWithTools:
        anthropic_messages: list[MessageParam] = self._convert_to_anthropic_messages(
            messages=messages,
        )

        model: ModelParam = self._select_model_from_preferences(params.modelPreferences)

        # Convert MCP tools to Anthropic format
        anthropic_tools: list[ToolParam] | None = None
        if params.tools:
            anthropic_tools = self._convert_tools_to_anthropic(params.tools)

        # Convert tool_choice to Anthropic format
        # Returns None if mode is "none", signaling tools should be omitted
        anthropic_tool_choice: ToolChoiceParam | None = None
        if params.toolChoice:
            converted = self._convert_tool_choice_to_anthropic(params.toolChoice)
            if converted is None:
                # tool_choice="none" means don't use tools
                anthropic_tools = None
            else:
                anthropic_tool_choice = converted

        # Build kwargs to avoid sentinel type compatibility issues across
        # anthropic SDK versions (NotGiven vs Omit)
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": anthropic_messages,
            "max_tokens": params.maxTokens,
        }
        if params.systemPrompt is not None:
            kwargs["system"] = params.systemPrompt
        if params.temperature is not None:
            kwargs["temperature"] = params.temperature
        if params.stopSequences is not None:
            kwargs["stop_sequences"] = params.stopSequences
        if anthropic_tools is not None:
            kwargs["tools"] = anthropic_tools
        if anthropic_tool_choice is not None:
            kwargs["tool_choice"] = anthropic_tool_choice

        response = await self.client.messages.create(**kwargs)

        # Return appropriate result type based on whether tools were provided
        if params.tools:
            return self._message_to_result_with_tools(response)
        return self._message_to_create_message_result(response)

    @staticmethod
    def _iter_models_from_preferences(
        model_preferences: ModelPreferences | str | list[str] | None,
    ) -> Iterator[str]:
        pass

    @staticmethod
    def _convert_to_anthropic_messages(
        messages: Sequence[SamplingMessage],
    ) -> list[MessageParam]:
        pass

    @staticmethod
    def _message_to_create_message_result(
        message: Message,
    ) -> CreateMessageResult:
        pass

    def _select_model_from_preferences(
        self, model_preferences: ModelPreferences | str | list[str] | None
    ) -> ModelParam:
        pass

    @staticmethod
    def _convert_tools_to_anthropic(tools: list[Tool]) -> list[ToolParam]:
        """Convert MCP tools to Anthropic tool format."""
        pass

    @staticmethod
    def _convert_tool_choice_to_anthropic(
        tool_choice: ToolChoice,
    ) -> ToolChoiceParam | None:
        """Convert MCP tool_choice to Anthropic format.

        Returns None for "none" mode, signaling that tools should be omitted
        from the request entirely (Anthropic doesn't have an explicit "none" option).
        """
        pass

    @staticmethod
    def _message_to_result_with_tools(
        message: Message,
    ) -> CreateMessageResultWithTools:
        """Convert Anthropic response to CreateMessageResultWithTools."""
        pass
