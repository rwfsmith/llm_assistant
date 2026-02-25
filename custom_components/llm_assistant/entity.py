"""Base entity for LLM Assistant – handles chat log, tool calling, streaming and MCP."""

from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import AsyncGenerator, Callable
from datetime import datetime  # noqa: F401  reserved for future date injection
from typing import Any, Literal

import openai
from homeassistant.components import conversation
from homeassistant.config_entries import ConfigSubentry
from homeassistant.const import CONF_API_KEY, CONF_MODEL
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import llm
from homeassistant.helpers.entity import Entity
from openai._streaming import AsyncStream
from openai.types.chat import (
    ChatCompletionAssistantMessageParam,
    ChatCompletionChunk,
    ChatCompletionContentPartImageParam,
    ChatCompletionContentPartTextParam,
    ChatCompletionFunctionToolParam,
    ChatCompletionMessageFunctionToolCallParam,
    ChatCompletionMessageParam,
    ChatCompletionSystemMessageParam,
    ChatCompletionToolMessageParam,
    ChatCompletionUserMessageParam,
)
from openai.types.chat.chat_completion_message_function_tool_call_param import Function
from openai.types.shared_params import FunctionDefinition
from voluptuous_openapi import convert

from . import LLMAssistantConfigEntry
from .const import (
    CONF_BASE_URL,
    CONF_CONTEXT_LENGTH,
    CONF_MAX_MESSAGE_HISTORY,
    CONF_MCP_SERVERS,
    CONF_PARALLEL_TOOL_CALLS,
    CONF_STRIP_EMOJIS,
    CONF_TEMPERATURE,
    CONF_USE_LMSTUDIO_API,
    DEFAULT_CONTEXT_LENGTH,
    DEFAULT_TEMPERATURE,
    DOMAIN,
    LOGGER,
)
from .lmstudio import (
    LMStudioNativeClient,
    build_mcp_integrations,
    parse_lmstudio_response,
)

# Maximum LLM ↔ tool-call iterations to prevent infinite loops
MAX_TOOL_ITERATIONS = 10


# ---------------------------------------------------------------------------
# Tool / schema helpers
# ---------------------------------------------------------------------------

def _remove_unsupported_tool_schema_keys(schema: dict[str, Any]) -> None:
    """Remove JSON Schema keywords not accepted by many inference servers."""
    for key in ("allOf", "anyOf", "oneOf"):
        schema.pop(key, None)


def _format_tool(
    tool: llm.Tool,
    custom_serializer: Callable[[Any], Any] | None,
) -> ChatCompletionFunctionToolParam:
    """Format an HA LLM tool into the OpenAI function-tool format."""
    parameters = convert(tool.parameters, custom_serializer=custom_serializer)
    _remove_unsupported_tool_schema_keys(parameters)
    spec = FunctionDefinition(name=tool.name, parameters=parameters)
    spec["description"] = (
        tool.description
        if tool.description and tool.description.strip()
        else "A callable function"
    )
    return ChatCompletionFunctionToolParam(type="function", function=spec)


# ---------------------------------------------------------------------------
# Message conversion helpers (HA ChatLog ↔ OpenAI API)
# ---------------------------------------------------------------------------

def _b64_file(file_path) -> str:  # noqa: ANN001
    return base64.b64encode(file_path.read_bytes()).decode("utf-8")


async def _content_to_openai_message(
    content: conversation.Content,
) -> ChatCompletionMessageParam | None:
    """Translate any HA conversation Content into an OpenAI message param."""

    if isinstance(content, conversation.ToolResultContent):

        def _safe_str(value: Any) -> str:
            LOGGER.warning(
                "Non-JSON-serialisable tool result for '%s': %s",
                content.tool_name,
                value,
            )
            return str(value)

        return ChatCompletionToolMessageParam(
            role="tool",
            tool_call_id=content.tool_call_id,
            content=json.dumps(content.tool_result, default=_safe_str),
        )

    role: Literal["user", "assistant", "system"] = content.role

    if role == "system" and content.content:
        return ChatCompletionSystemMessageParam(role="system", content=content.content)

    if role == "user" and content.content:
        parts: list[Any] = []

        if content.attachments:
            loop = asyncio.get_running_loop()
            for attachment in content.attachments or ():
                if not attachment.mime_type.startswith("image/"):
                    raise HomeAssistantError(
                        translation_domain=DOMAIN,
                        translation_key="unsupported_attachment_type",
                    )
                b64 = await loop.run_in_executor(None, _b64_file, attachment.path)
                parts.append(
                    ChatCompletionContentPartImageParam(
                        type="image_url",
                        image_url={
                            "url": f"data:{attachment.mime_type};base64,{b64}",
                            "detail": "auto",
                        },
                    )
                )

        parts.append(
            ChatCompletionContentPartTextParam(type="text", text=content.content)
        )
        return ChatCompletionUserMessageParam(role="user", content=parts)

    if role == "assistant":
        param = ChatCompletionAssistantMessageParam(
            role="assistant", content=content.content
        )
        if isinstance(content, conversation.AssistantContent) and content.tool_calls:
            param["tool_calls"] = [
                ChatCompletionMessageFunctionToolCallParam(
                    type="function",
                    id=tc.id,
                    function=Function(
                        arguments=json.dumps(tc.tool_args),
                        name=tc.tool_name,
                    ),
                )
                for tc in content.tool_calls
            ]
        return param

    LOGGER.warning("Could not convert content to OpenAI message: %s", content)
    return None


# ---------------------------------------------------------------------------
# Base entity
# ---------------------------------------------------------------------------

class LLMAssistantEntity(Entity):
    """Base entity that drives interaction with the LLM server."""

    _attr_has_entity_name = True

    def __init__(
        self, entry: LLMAssistantConfigEntry, subentry: ConfigSubentry
    ) -> None:
        """Initialise."""
        self.entry = entry
        self.subentry = subentry
        self.model: str = subentry.data[CONF_MODEL]
        self._attr_unique_id = subentry.subentry_id
        self._attr_device_info = dr.DeviceInfo(
            identifiers={(DOMAIN, subentry.subentry_id)},
            name=subentry.title,
            entry_type=dr.DeviceEntryType.SERVICE,
        )

    # ------------------------------------------------------------------
    # Streaming: OpenAI-compatible endpoint
    # ------------------------------------------------------------------

    async def _transform_openai_stream(
        self,
        stream: AsyncStream[ChatCompletionChunk],
        strip_emojis: bool,
    ) -> AsyncGenerator[conversation.AssistantContentDeltaDict, None]:
        """Translate a streaming OpenAI response into HA ChatLog delta format."""
        new_msg = True
        in_think = False
        pending_think = ""
        seen_visible = False
        pending_tool_calls: dict[str, dict] = {}
        tool_call_id: str | None = None
        tool_call_name: str | None = None

        async for event in stream:
            if not event.choices:
                continue

            choice = event.choices[0]
            delta = choice.delta
            chunk: conversation.AssistantContentDeltaDict = {}

            if new_msg:
                chunk["role"] = delta.role
                new_msg = False

            # ---- Tool call accumulation ----
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    tool_call_id = tc.id if tc.id else tool_call_id
                    tool_call_name = (
                        tc.function.name
                        if tc.function and tc.function.name and tc.function.name != tool_call_name
                        else tool_call_name
                    )
                    key = (tool_call_id or "") + (tool_call_name or "")
                    if key not in pending_tool_calls:
                        pending_tool_calls[key] = {
                            "id": tool_call_id,
                            "name": tc.function.name if tc.function else "",
                            "args": tc.function.arguments or "" if tc.function else "",
                        }
                    else:
                        if tc.function and tc.function.arguments:
                            pending_tool_calls[key]["args"] += tc.function.arguments

            # ---- Text content ----
            if (text := delta.content) is not None:
                if text == "<think>":
                    in_think = True
                    pending_think = ""
                elif in_think:
                    if text == "</think>":
                        in_think = False
                        if pending_think.strip():
                            LOGGER.debug("LLM thinking: %s", pending_think)
                        pending_think = ""
                    else:
                        pending_think += text
                else:
                    if strip_emojis:
                        loop = asyncio.get_running_loop()
                        try:
                            import demoji  # optional dep
                            text = await loop.run_in_executor(None, demoji.replace, text, "")
                        except ImportError:
                            pass
                    if text.strip():
                        seen_visible = True
                    chunk["content"] = text

            # ---- Finish ----
            if choice.finish_reason:
                if pending_tool_calls:
                    chunk["tool_calls"] = [
                        llm.ToolInput(
                            id=tc["id"],
                            tool_name=tc["name"],
                            tool_args=json.loads(tc["args"]) if tc["args"] else {},
                        )
                        for tc in pending_tool_calls.values()
                    ]
                    LOGGER.debug("Tool calls: %s", pending_tool_calls)

            if seen_visible or chunk.get("tool_calls") or chunk.get("role"):
                yield chunk

    # ------------------------------------------------------------------
    # History trimming
    # ------------------------------------------------------------------

    @staticmethod
    def _trim_history(messages: list[dict], max_rounds: int) -> list[dict]:
        """Remove old assistant turns to stay within context limits."""
        if max_rounds < 1:
            return messages

        num_assistant = sum(1 for m in messages if m.get("role") == "assistant")
        # -1 because the current in-progress turn is included
        num_previous = num_assistant - 1
        if num_previous >= max_rounds:
            keep = 2 * max_rounds + 1  # each round ≈ 2 messages
            drop = len(messages) - keep
            messages = [messages[0], *messages[int(drop):]]
            if len(messages) > 1 and messages[1].get("role") == "tool":
                del messages[1]

        return messages

    # ------------------------------------------------------------------
    # Core: OpenAI-compatible endpoint (standard)
    # ------------------------------------------------------------------

    async def _handle_chat_openai(
        self,
        chat_log: conversation.ChatLog,
        messages: list[dict],
        tools: list[ChatCompletionFunctionToolParam] | None,
        temperature: float,
        parallel_tool_calls: bool,
        strip_emojis: bool,
        mcp_servers: list[dict],
    ) -> None:
        """Drive the conversation via the standard OpenAI-compat endpoint.

        MCP servers are passed via ``extra_body.integrations`` so that endpoints
        that understand the parameter (e.g. an extended LM Studio compat layer)
        will use them.  Endpoints that don't understand the field will silently
        ignore it.
        """
        client: openai.AsyncOpenAI = self.entry.runtime_data

        model_args: dict[str, Any] = {
            "model": self.model,
            "temperature": temperature,
            "parallel_tool_calls": parallel_tool_calls,
        }
        if tools:
            model_args["tools"] = tools

        # Pass MCP integrations via extra_body for compatible servers
        mcp_integrations = build_mcp_integrations(mcp_servers)
        if mcp_integrations:
            model_args["extra_body"] = {"integrations": mcp_integrations}
            LOGGER.debug(
                "Passing %d MCP integration(s) via extra_body", len(mcp_integrations)
            )

        for _iteration in range(MAX_TOOL_ITERATIONS):
            model_args["messages"] = messages

            try:
                stream = await client.chat.completions.create(**model_args, stream=True)
            except openai.OpenAIError as err:
                LOGGER.exception("OpenAI API error: %s", err)
                raise HomeAssistantError("Error communicating with LLM server") from err

            try:
                new_messages = [
                    msg
                    async for content in chat_log.async_add_delta_content_stream(
                        self.entity_id,
                        self._transform_openai_stream(stream, strip_emojis),
                    )
                    if (msg := await _content_to_openai_message(content))
                ]
                messages.extend(new_messages)
            except Exception as err:
                LOGGER.exception("Error handling API response: %s", err)
                raise HomeAssistantError("Error processing LLM response") from err

            if not chat_log.unresponded_tool_results:
                break

    # ------------------------------------------------------------------
    # Core: LM Studio native endpoint (/api/v1/chat)
    # ------------------------------------------------------------------

    async def _handle_chat_lmstudio(
        self,
        chat_log: conversation.ChatLog,
        messages: list[dict],
        tools: list[ChatCompletionFunctionToolParam] | None,
        temperature: float,
        context_length: int,
        strip_emojis: bool,
        mcp_servers: list[dict],
        user_input: conversation.ConversationInput | None,
    ) -> None:
        """Drive the conversation via LM Studio's /api/v1/chat endpoint.

        In this mode, LM Studio orchestrates MCP tool calls itself and returns
        the final, resolved response.  HA tool calls (for controlling devices)
        are still handled iteratively within this integration.
        """
        api_key = self.entry.data.get(CONF_API_KEY, "") or ""
        lm_client = LMStudioNativeClient(
            hass=self.hass,
            base_url=self.entry.data[CONF_BASE_URL],
            api_key=api_key,
        )

        mcp_integrations = build_mcp_integrations(mcp_servers)
        lm_tools: list[dict] | None = None
        if tools:
            # Convert to plain dicts (LM Studio accepts the same format as OpenAI)
            lm_tools = [json.loads(json.dumps(t)) for t in tools]

        for _iteration in range(MAX_TOOL_ITERATIONS):
            try:
                response = await lm_client.chat(
                    model=self.model,
                    messages=messages,
                    integrations=mcp_integrations or None,
                    tools=lm_tools,
                    temperature=temperature,
                    context_length=context_length,
                )
            except Exception as err:
                LOGGER.exception("LM Studio native API error: %s", err)
                raise HomeAssistantError("Error communicating with LM Studio") from err

            text, mcp_tool_calls = parse_lmstudio_response(response)

            if mcp_tool_calls:
                # Log MCP tool results as context (they were already executed by LM Studio)
                mcp_summary = "\n".join(
                    f"[MCP:{tc['tool']}] {tc['output']}" for tc in mcp_tool_calls
                )
                LOGGER.debug("LM Studio MCP tool results:\n%s", mcp_summary)

            if strip_emojis and text:
                try:
                    import demoji
                    text = demoji.replace(text, "")
                except ImportError:
                    pass

            # Inject the response as an assistant message into the chat log
            if text:
                # Build a synthetic streaming delta for the chat log
                async def _single_message_stream(
                    t: str = text,
                ) -> AsyncGenerator[conversation.AssistantContentDeltaDict, None]:
                    yield {"role": "assistant", "content": t}

                new_messages = [
                    msg
                    async for content in chat_log.async_add_delta_content_stream(
                        self.entity_id,
                        _single_message_stream(),
                    )
                    if (msg := await _content_to_openai_message(content))
                ]
                messages.extend(new_messages)

            if not chat_log.unresponded_tool_results:
                break

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def _async_handle_chat_log(
        self,
        chat_log: conversation.ChatLog,
        user_input: conversation.ConversationInput | None = None,
    ) -> None:
        """Route the conversation to the correct backend and drive it to completion."""
        options = self.subentry.data
        strip_emojis: bool = bool(options.get(CONF_STRIP_EMOJIS, False))
        temperature: float = float(options.get(CONF_TEMPERATURE, DEFAULT_TEMPERATURE))
        max_history: int = int(options.get(CONF_MAX_MESSAGE_HISTORY, 0))
        parallel_tool_calls: bool = bool(options.get(CONF_PARALLEL_TOOL_CALLS, True))
        context_length: int = int(options.get(CONF_CONTEXT_LENGTH, DEFAULT_CONTEXT_LENGTH))
        mcp_servers: list[dict] = list(options.get(CONF_MCP_SERVERS) or [])
        use_lmstudio: bool = bool(self.entry.data.get(CONF_USE_LMSTUDIO_API, False))

        # Build HA tool list
        tools: list[ChatCompletionFunctionToolParam] | None = None
        if chat_log.llm_api:
            tools = [
                _format_tool(tool, chat_log.llm_api.custom_serializer)
                for tool in chat_log.llm_api.tools
            ]

        # Convert the HA ChatLog into an OpenAI-style message list
        raw_messages: list[dict] = []
        for content in chat_log.content:
            msg = await _content_to_openai_message(content)
            if msg:
                raw_messages.append(msg)
        messages = self._trim_history(raw_messages, max_history)

        if use_lmstudio:
            await self._handle_chat_lmstudio(
                chat_log=chat_log,
                messages=messages,
                tools=tools,
                temperature=temperature,
                context_length=context_length,
                strip_emojis=strip_emojis,
                mcp_servers=mcp_servers,
                user_input=user_input,
            )
        else:
            await self._handle_chat_openai(
                chat_log=chat_log,
                messages=messages,
                tools=tools,
                temperature=temperature,
                parallel_tool_calls=parallel_tool_calls,
                strip_emojis=strip_emojis,
                mcp_servers=mcp_servers,
            )
