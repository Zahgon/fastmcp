"""Google GenAI sampling handler with tool support for FastMCP 3.0."""

import base64
from collections.abc import Sequence
from uuid import uuid4

try:
    from google.genai import Client as GoogleGenaiClient
    from google.genai.types import (
        Blob,
        Candidate,
        Content,
        FunctionCall,
        FunctionCallingConfig,
        FunctionCallingConfigMode,
        FunctionDeclaration,
        FunctionResponse,
        GenerateContentConfig,
        GenerateContentResponse,
        ModelContent,
        Part,
        ThinkingConfig,
        ToolConfig,
        UserContent,
    )
    from google.genai.types import Tool as GoogleTool
except ImportError as e:
    raise ImportError(
        "The `google-genai` package is not installed. "
        "Install it with `pip install fastmcp[gemini]` or add `google-genai` "
        "to your dependencies."
    ) from e

from mcp import ClientSession, ServerSession
from mcp.shared.context import LifespanContextT, RequestContext
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
    ToolChoice,
    ToolResultContent,
    ToolUseContent,
)
from mcp.types import CreateMessageRequestParams as SamplingParams
from mcp.types import Tool as MCPTool

__all__ = ["GoogleGenaiSamplingHandler"]


class GoogleGenaiSamplingHandler:
    """Sampling handler that uses the Google GenAI API with tool support.

    Example:
        ```python
        from google.genai import Client
        from fastmcp import FastMCP
        from fastmcp.client.sampling.handlers.google_genai import (
            GoogleGenaiSamplingHandler,
        )

        handler = GoogleGenaiSamplingHandler(
            default_model="gemini-2.0-flash",
            client=Client(),
        )

        server = FastMCP(sampling_handler=handler)
        ```
    """

    def __init__(
        self,
        default_model: str,
        client: GoogleGenaiClient | None = None,
        thinking_budget: int | None = None,
    ) -> None:
        self.client: GoogleGenaiClient = client or GoogleGenaiClient()
        self.default_model: str = default_model
        self.thinking_budget: int | None = thinking_budget

    async def __call__(
        self,
        messages: list[SamplingMessage],
        params: SamplingParams,
        context: RequestContext[ServerSession, LifespanContextT]
        | RequestContext[ClientSession, LifespanContextT],
    ) -> CreateMessageResult | CreateMessageResultWithTools:
        contents: list[Content] = _convert_messages_to_google_genai_content(messages)

        # Convert MCP tools to Google GenAI format
        google_tools: list[GoogleTool] | None = None
        tool_config: ToolConfig | None = None

        if params.tools:
            google_tools = [
                _convert_tool_to_google_genai(tool) for tool in params.tools
            ]
            tool_config = _convert_tool_choice_to_google_genai(params.toolChoice)

        # Select the model based on preferences
        selected_model = self._get_model(model_preferences=params.modelPreferences)

        # Configure thinking if a budget is specified
        thinking_config = (
            ThinkingConfig(thinking_budget=self.thinking_budget)
            if self.thinking_budget is not None
            else None
        )

        response: GenerateContentResponse = (
            await self.client.aio.models.generate_content(
                model=selected_model,
                contents=contents,
                config=GenerateContentConfig(
                    system_instruction=params.systemPrompt,
                    temperature=params.temperature,
                    max_output_tokens=params.maxTokens,
                    stop_sequences=params.stopSequences,
                    thinking_config=thinking_config,
                    tools=google_tools,  # ty: ignore[invalid-argument-type]
                    tool_config=tool_config,
                ),
            )
        )

        # Return appropriate result type based on whether tools were provided
        if params.tools:
            return _response_to_result_with_tools(response, selected_model)
        return _response_to_create_message_result(response, selected_model)

    def _get_model(self, model_preferences: ModelPreferences | None) -> str:
        pass


def _convert_tool_to_google_genai(tool: MCPTool) -> GoogleTool:
    """Convert an MCP Tool to Google GenAI format.

    We prune ``title`` fields from the schema because Gemini 2.5 Flash
    produces ``MALFORMED_FUNCTION_CALL`` when Pydantic's auto-generated
    title annotations are present.
    """
    pass


def _convert_tool_choice_to_google_genai(tool_choice: ToolChoice | None) -> ToolConfig:
    """Convert MCP ToolChoice to Google GenAI ToolConfig."""
    pass


def _sampling_content_to_google_genai_part(
    content: TextContent
    | ImageContent
    | AudioContent
    | ToolUseContent
    | ToolResultContent,
) -> Part:
    """Convert MCP content to Google GenAI Part."""
    pass


def _convert_messages_to_google_genai_content(
    messages: Sequence[SamplingMessage],
) -> list[Content]:
    """Convert MCP messages to Google GenAI content."""
    pass


def _get_candidate_from_response(response: GenerateContentResponse) -> Candidate:
    """Extract the first candidate from a response."""
    pass


def _response_to_create_message_result(
    response: GenerateContentResponse,
    model: str,
) -> CreateMessageResult:
    """Convert Google GenAI response to CreateMessageResult (no tools)."""
    pass


def _response_to_result_with_tools(
    response: GenerateContentResponse,
    model: str,
) -> CreateMessageResultWithTools:
    """Convert Google GenAI response to CreateMessageResultWithTools."""
    pass
