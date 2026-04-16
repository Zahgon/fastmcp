"""OpenAI sampling handler for FastMCP."""

import json
from collections.abc import Iterator, Sequence
from typing import Any, Literal, get_args

from mcp import ClientSession, ServerSession
from mcp.shared.context import LifespanContextT, RequestContext
from mcp.types import (
    AudioContent,
    CreateMessageResult,
    CreateMessageResultWithTools,
    ImageContent,
    ModelPreferences,
    SamplingMessage,
    StopReason,
    TextContent,
    Tool,
    ToolChoice,
    ToolResultContent,
    ToolUseContent,
)
from mcp.types import CreateMessageRequestParams as SamplingParams

try:
    from openai import AsyncOpenAI
    from openai.types.chat import (
        ChatCompletion,
        ChatCompletionAssistantMessageParam,
        ChatCompletionContentPartImageParam,
        ChatCompletionContentPartInputAudioParam,
        ChatCompletionContentPartParam,
        ChatCompletionContentPartTextParam,
        ChatCompletionMessageParam,
        ChatCompletionMessageToolCallParam,
        ChatCompletionSystemMessageParam,
        ChatCompletionToolChoiceOptionParam,
        ChatCompletionToolMessageParam,
        ChatCompletionToolParam,
        ChatCompletionUserMessageParam,
    )
    from openai.types.shared.chat_model import ChatModel
    from openai.types.shared_params import FunctionDefinition
except ImportError as e:
    raise ImportError(
        "The `openai` package is not installed. "
        "Please install `fastmcp[openai]` or add `openai` to your dependencies manually."
    ) from e

# OpenAI only supports wav and mp3 for input audio
_OPENAI_AUDIO_FORMATS: dict[str, Literal["wav", "mp3"]] = {
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/mp3": "mp3",
    "audio/mpeg": "mp3",
}

_OPENAI_IMAGE_MEDIA_TYPES: frozenset[str] = frozenset(
    {"image/jpeg", "image/png", "image/gif", "image/webp"}
)


def _image_content_to_openai_part(
    content: ImageContent,
) -> ChatCompletionContentPartImageParam:
    """Convert MCP ImageContent to OpenAI image_url content part."""
    if content.mimeType not in _OPENAI_IMAGE_MEDIA_TYPES:
        raise ValueError(
            f"Unsupported image MIME type for OpenAI: {content.mimeType!r}. "
            f"Supported types: {', '.join(sorted(_OPENAI_IMAGE_MEDIA_TYPES))}"
        )
    data_url = f"data:{content.mimeType};base64,{content.data}"
    return ChatCompletionContentPartImageParam(
        type="image_url",
        image_url={"url": data_url},
    )


def _audio_content_to_openai_part(
    content: AudioContent,
) -> ChatCompletionContentPartInputAudioParam:
    """Convert MCP AudioContent to OpenAI input_audio content part."""
    audio_format = _OPENAI_AUDIO_FORMATS.get(content.mimeType)
    if audio_format is None:
        raise ValueError(
            f"Unsupported audio MIME type for OpenAI: {content.mimeType!r}. "
            f"Supported types: {', '.join(sorted(_OPENAI_AUDIO_FORMATS))}"
        )
    return ChatCompletionContentPartInputAudioParam(
        type="input_audio",
        input_audio={"data": content.data, "format": audio_format},
    )


class OpenAISamplingHandler:
    """Sampling handler that uses the OpenAI API."""

    def __init__(
        self,
        default_model: ChatModel,
        client: AsyncOpenAI | None = None,
    ) -> None:
        self.client: AsyncOpenAI = client or AsyncOpenAI()
        self.default_model: ChatModel = default_model

    async def __call__(
        self,
        messages: list[SamplingMessage],
        params: SamplingParams,
        context: RequestContext[ServerSession, LifespanContextT]
        | RequestContext[ClientSession, LifespanContextT],
    ) -> CreateMessageResult | CreateMessageResultWithTools:
        openai_messages: list[ChatCompletionMessageParam] = (
            self._convert_to_openai_messages(
                system_prompt=params.systemPrompt,
                messages=messages,
            )
        )

        model: ChatModel = self._select_model_from_preferences(params.modelPreferences)

        # Convert MCP tools to OpenAI format
        openai_tools: list[ChatCompletionToolParam] | None = None
        if params.tools:
            openai_tools = self._convert_tools_to_openai(params.tools)

        # Convert tool_choice to OpenAI format
        openai_tool_choice: ChatCompletionToolChoiceOptionParam | None = None
        if params.toolChoice:
            openai_tool_choice = self._convert_tool_choice_to_openai(params.toolChoice)

        # Build kwargs to avoid sentinel type compatibility issues across
        # openai SDK versions (NotGiven vs Omit)
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": openai_messages,
        }
        if params.maxTokens is not None:
            kwargs["max_completion_tokens"] = params.maxTokens
        if params.temperature is not None:
            kwargs["temperature"] = params.temperature
        if params.stopSequences:
            kwargs["stop"] = params.stopSequences
        if openai_tools is not None:
            kwargs["tools"] = openai_tools
        if openai_tool_choice is not None:
            kwargs["tool_choice"] = openai_tool_choice

        response = await self.client.chat.completions.create(**kwargs)

        # Return appropriate result type based on whether tools were provided
        if params.tools:
            return self._chat_completion_to_result_with_tools(response)
        return self._chat_completion_to_create_message_result(response)

    @staticmethod
    def _iter_models_from_preferences(
        model_preferences: ModelPreferences | str | list[str] | None,
    ) -> Iterator[str]:
        pass

    @staticmethod
    def _convert_to_openai_messages(
        system_prompt: str | None, messages: Sequence[SamplingMessage]
    ) -> list[ChatCompletionMessageParam]:
        pass

    @staticmethod
    def _chat_completion_to_create_message_result(
        chat_completion: ChatCompletion,
    ) -> CreateMessageResult:
        pass

    def _select_model_from_preferences(
        self, model_preferences: ModelPreferences | str | list[str] | None
    ) -> ChatModel:
        pass

    @staticmethod
    def _convert_tools_to_openai(tools: list[Tool]) -> list[ChatCompletionToolParam]:
        """Convert MCP tools to OpenAI tool format."""
        pass

    @staticmethod
    def _convert_tool_choice_to_openai(
        tool_choice: ToolChoice,
    ) -> ChatCompletionToolChoiceOptionParam:
        """Convert MCP tool_choice to OpenAI format."""
        pass

    @staticmethod
    def _chat_completion_to_result_with_tools(
        chat_completion: ChatCompletion,
    ) -> CreateMessageResultWithTools:
        """Convert OpenAI response to CreateMessageResultWithTools."""
        pass
