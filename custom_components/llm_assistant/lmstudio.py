"""LM Studio native API client (/api/v1/chat).

LM Studio exposes two API families:
  - /v1/...            – OpenAI-compatible endpoints
  - /api/v1/chat       – Native endpoint with full MCP / integrations support

This module uses the native endpoint so that MCP servers (both ephemeral and
pre-configured mcp.json plugins) are orchestrated by LM Studio itself.  The
response format differs from the OpenAI format; this module translates it into
structures that the entity layer can work with uniformly.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urljoin

from homeassistant.helpers.httpx_client import get_async_client
from homeassistant.core import HomeAssistant

from .const import LOGGER


class LMStudioError(Exception):
    """Raised when the LM Studio native API returns an error."""


class LMStudioNativeClient:
    """Thin async client for the LM Studio /api/v1/chat endpoint."""

    def __init__(self, hass: HomeAssistant, base_url: str, api_key: str = "") -> None:
        """Initialise the client.

        Args:
            hass:     HA instance (used to get the shared httpx client).
            base_url: Base URL of the LM Studio server, e.g. ``http://localhost:1234/v1``.
                      The ``/v1`` suffix is stripped automatically so we can target
                      ``/api/v1/chat``.
            api_key:  Optional bearer token.
        """
        # Normalise: strip trailing /v1 or /v1/ so we get the server root
        root = base_url.rstrip("/")
        if root.endswith("/v1"):
            root = root[: -len("/v1")]
        self._endpoint = root + "/api/v1/chat"
        self._api_key = api_key
        self._hass = hass

    async def chat(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        integrations: list[Any] | None = None,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.6,
        context_length: int = 8000,
    ) -> dict[str, Any]:
        """Send a chat request and return the parsed response dict.

        The payload follows ``POST /api/v1/chat`` format:
        https://lmstudio.ai/docs/developer/rest/chat

        Returns the full response body as a dict; the ``output`` key contains a
        list of output items.
        """
        payload: dict[str, Any] = {
            "model": model,
            "input": _messages_to_lmstudio_input(messages),
            "temperature": temperature,
            "context_length": context_length,
        }

        if integrations:
            payload["integrations"] = integrations

        if tools:
            # LM Studio native API also accepts tools for HA-style function calling
            payload["tools"] = tools

        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        client = get_async_client(self._hass)
        LOGGER.debug("LM Studio native API request to %s: %s", self._endpoint, payload)

        response = await client.post(
            self._endpoint,
            json=payload,
            headers=headers,
            timeout=120.0,
        )

        if response.status_code >= 400:
            body = response.text
            LOGGER.error(
                "LM Studio native API error %s: %s", response.status_code, body
            )
            raise LMStudioError(
                f"LM Studio responded with {response.status_code}: {body}"
            )

        result: dict[str, Any] = response.json()
        LOGGER.debug("LM Studio native API response: %s", result)
        return result


# ---------------------------------------------------------------------------
# Response conversion helpers
# ---------------------------------------------------------------------------

def parse_lmstudio_response(response: dict[str, Any]) -> tuple[str, list[dict]]:
    """Parse a native LM Studio chat response.

    Returns:
        (text_content, tool_calls)
        where tool_calls is a list of dicts with keys: name, arguments, output
    """
    output_items: list[dict] = response.get("output", [])
    text_parts: list[str] = []
    tool_calls: list[dict] = []

    for item in output_items:
        item_type = item.get("type", "")

        if item_type == "message":
            content = item.get("content", "")
            if content:
                text_parts.append(content)

        elif item_type == "reasoning":
            # Skip <think> blocks – log for debugging only
            reason = item.get("content", "")
            if reason.strip():
                LOGGER.debug("LM Studio reasoning: %s", reason)

        elif item_type == "tool_call":
            # MCP tool calls are already resolved by LM Studio; include their
            # output as context so it appears in the conversation log.
            tool_calls.append(
                {
                    "tool": item.get("tool", ""),
                    "arguments": item.get("arguments", {}),
                    "output": item.get("output", ""),
                    "provider_info": item.get("provider_info", {}),
                }
            )

    return "\n".join(text_parts), tool_calls


def build_mcp_integrations(mcp_servers: list[dict[str, Any]]) -> list[Any]:
    """Convert the stored MCP server configs into the integrations list format
    expected by the LM Studio /api/v1/chat endpoint."""
    from .const import (
        CONF_MCP_ALLOWED_TOOLS,
        CONF_MCP_HEADERS,
        CONF_MCP_LABEL,
        CONF_MCP_PLUGIN_ID,
        CONF_MCP_TYPE,
        CONF_MCP_URL,
        MCP_TYPE_EPHEMERAL,
        MCP_TYPE_PLUGIN,
    )

    integrations: list[Any] = []

    for server in mcp_servers:
        server_type = server.get(CONF_MCP_TYPE, MCP_TYPE_EPHEMERAL)

        if server_type == MCP_TYPE_EPHEMERAL:
            label = server.get(CONF_MCP_LABEL, "").strip()
            url = server.get(CONF_MCP_URL, "").strip()
            if not label or not url:
                LOGGER.warning(
                    "Skipping ephemeral MCP server – 'label' and 'url' are required"
                )
                continue

            entry: dict[str, Any] = {
                "type": "ephemeral_mcp",
                "server_label": label,
                "server_url": url,
            }

            allowed_raw = server.get(CONF_MCP_ALLOWED_TOOLS, "") or ""
            allowed = [t.strip() for t in allowed_raw.split(",") if t.strip()]
            if allowed:
                entry["allowed_tools"] = allowed

            headers_raw = server.get(CONF_MCP_HEADERS, "") or ""
            if isinstance(headers_raw, str) and headers_raw.strip():
                try:
                    entry["headers"] = json.loads(headers_raw)
                except json.JSONDecodeError:
                    LOGGER.warning(
                        "Could not parse MCP server headers JSON for '%s': %s",
                        label,
                        headers_raw,
                    )
            elif isinstance(headers_raw, dict) and headers_raw:
                entry["headers"] = headers_raw

            integrations.append(entry)

        elif server_type == MCP_TYPE_PLUGIN:
            plugin_id = server.get(CONF_MCP_PLUGIN_ID, "").strip()
            if not plugin_id:
                LOGGER.warning(
                    "Skipping plugin MCP server – 'plugin_id' is required"
                )
                continue
            # LM Studio accepts a plain string plugin ID in the integrations list
            integrations.append(plugin_id)

    return integrations


# ---------------------------------------------------------------------------
# Helpers: convert OpenAI-style messages to LM Studio input
# ---------------------------------------------------------------------------

def _messages_to_lmstudio_input(messages: list[dict[str, Any]]) -> str | list[dict]:
    """Convert a list of OpenAI-style messages to the LM Studio ``input`` field.

    LM Studio's /api/v1/chat accepts either a plain string (single user turn)
    or a list of message objects:
      [{"role": "user"|"assistant"|"system", "content": "..."}]

    We pass the structured form so that conversation history is preserved.
    """
    lm_messages: list[dict[str, Any]] = []

    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")

        if role == "tool":
            # Convert tool results to assistant context
            lm_messages.append(
                {
                    "role": "user",
                    "content": f"[Tool result for {msg.get('tool_call_id', 'tool')}]: {content}",
                }
            )
        elif isinstance(content, list):
            # Multimodal content – extract text parts only for now
            text = " ".join(
                part.get("text", "") for part in content if part.get("type") == "text"
            )
            if text:
                lm_messages.append({"role": role, "content": text})
        elif content:
            lm_messages.append({"role": role, "content": content})

    return lm_messages
