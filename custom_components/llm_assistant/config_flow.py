"""Config flow for LLM Assistant integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.const import CONF_API_KEY, CONF_LLM_HASS_API, CONF_MODEL, CONF_PROMPT
from homeassistant.core import callback
from homeassistant.helpers import llm
from homeassistant.helpers.httpx_client import get_async_client
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    ObjectSelector,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TemplateSelector,
)
from openai import AsyncOpenAI, OpenAIError

from .const import (
    CONF_BASE_URL,
    CONF_CONTEXT_LENGTH,
    CONF_MAX_MESSAGE_HISTORY,
    CONF_MCP_SERVERS,
    CONF_PARALLEL_TOOL_CALLS,
    CONF_SERVER_NAME,
    CONF_STRIP_EMOJIS,
    CONF_TEMPERATURE,
    CONF_USE_LMSTUDIO_API,
    DEFAULT_CONTEXT_LENGTH,
    DEFAULT_MAX_HISTORY,
    DEFAULT_TEMPERATURE,
    DOMAIN,
    LOGGER,
    MCP_TYPE_OPTIONS,
    RECOMMENDED_CONVERSATION_OPTIONS,
)


class LLMAssistantConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for LLM Assistant (server entry)."""

    VERSION = 1

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Return subentries supported by this handler."""
        return {"conversation": ConversationSubentryFlow}

    # ------------------------------------------------------------------
    # Server schema
    # ------------------------------------------------------------------
    @staticmethod
    def _server_schema(defaults: dict | None = None) -> vol.Schema:
        defaults = defaults or {}
        return vol.Schema(
            {
                vol.Required(
                    CONF_SERVER_NAME,
                    default=defaults.get(CONF_SERVER_NAME, "LLM Server"),
                ): str,
                vol.Required(
                    CONF_BASE_URL,
                    default=defaults.get(CONF_BASE_URL, "http://localhost:1234/v1"),
                ): str,
                vol.Optional(
                    CONF_API_KEY,
                    default=defaults.get(CONF_API_KEY, ""),
                ): str,
                vol.Optional(
                    CONF_USE_LMSTUDIO_API,
                    default=defaults.get(CONF_USE_LMSTUDIO_API, False),
                ): BooleanSelector(),
            }
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step (server configuration)."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._async_abort_entries_match(
                {CONF_BASE_URL: user_input[CONF_BASE_URL]}
            )
            try:
                client = AsyncOpenAI(
                    base_url=user_input[CONF_BASE_URL],
                    api_key=user_input.get(CONF_API_KEY) or "not-required",
                    http_client=get_async_client(self.hass),
                )
                LOGGER.debug("Testing connection to %s", user_input[CONF_BASE_URL])
                await client.with_options(timeout=15.0).models.list()
            except OpenAIError as err:
                LOGGER.exception("Failed to connect: %s", err)
                errors["base"] = "cannot_connect"
            except Exception as err:
                LOGGER.exception("Unexpected error: %s", err)
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(
                    title=user_input.get(CONF_SERVER_NAME, "LLM Server"),
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=self._server_schema(),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reconfiguration of the server entry."""
        errors: dict[str, str] = {}
        entry = self._get_reconfigure_entry()

        if user_input is not None:
            try:
                client = AsyncOpenAI(
                    base_url=user_input[CONF_BASE_URL],
                    api_key=user_input.get(CONF_API_KEY) or "not-required",
                    http_client=get_async_client(self.hass),
                )
                await client.with_options(timeout=15.0).models.list()
            except OpenAIError as err:
                LOGGER.exception("Failed to connect: %s", err)
                errors["base"] = "cannot_connect"
            except Exception as err:
                LOGGER.exception("Unexpected error: %s", err)
                errors["base"] = "unknown"
            else:
                return self.async_update_reload_and_abort(
                    entry=entry,
                    title=user_input.get(CONF_SERVER_NAME, "LLM Server"),
                    data=user_input,
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                self._server_schema(),
                entry.data.copy(),
            ),
            errors=errors,
        )


# ---------------------------------------------------------------------------
# Conversation agent subentry flow
# ---------------------------------------------------------------------------

class ConversationSubentryFlow(ConfigSubentryFlow):
    """Handle subentry flow for a Conversation Agent."""

    def _get_llm_api_options(self) -> list[SelectOptionDict]:
        return [
            SelectOptionDict(label=api.name, value=api.id)
            for api in llm.async_get_apis(self.hass)
        ]

    async def _fetch_models(self) -> list[SelectOptionDict]:
        """Fetch available models from the server."""
        entry = self._get_entry()
        client: AsyncOpenAI = entry.runtime_data
        try:
            response = await client.models.list()
            return [
                SelectOptionDict(label=model.id, value=model.id)
                for model in response.data
            ]
        except OpenAIError as err:
            LOGGER.warning("Could not retrieve model list: %s", err)
            return []
        except Exception as err:
            LOGGER.warning("Unexpected error fetching models: %s", err)
            return []

    async def _build_schema(self, defaults: dict | None = None) -> vol.Schema:
        """Build the agent configuration schema."""
        defaults = defaults or {}
        models = await self._fetch_models()
        llm_apis = self._get_llm_api_options()

        return vol.Schema(
            {
                # ----- Model selection -----
                vol.Required(
                    CONF_MODEL,
                    default=defaults.get(CONF_MODEL, ""),
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=models,
                        mode=SelectSelectorMode.DROPDOWN,
                        custom_value=True,
                    )
                ),
                # ----- System prompt -----
                vol.Optional(
                    CONF_PROMPT,
                    default=defaults.get(
                        CONF_PROMPT,
                        RECOMMENDED_CONVERSATION_OPTIONS[CONF_PROMPT],
                    ),
                ): TemplateSelector(),
                # ----- HA LLM APIs (tool calling for HA entities) -----
                vol.Optional(
                    CONF_LLM_HASS_API,
                    default=defaults.get(
                        CONF_LLM_HASS_API,
                        RECOMMENDED_CONVERSATION_OPTIONS[CONF_LLM_HASS_API],
                    ),
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=llm_apis,
                        multiple=True,
                        mode=SelectSelectorMode.LIST,
                    )
                ),
                # ----- Temperature -----
                vol.Required(
                    CONF_TEMPERATURE,
                    default=defaults.get(CONF_TEMPERATURE, DEFAULT_TEMPERATURE),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0.0, max=2.0, step=0.01, mode=NumberSelectorMode.SLIDER
                    )
                ),
                # ----- Context length (for LM Studio native API) -----
                vol.Optional(
                    CONF_CONTEXT_LENGTH,
                    default=defaults.get(CONF_CONTEXT_LENGTH, DEFAULT_CONTEXT_LENGTH),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=1024,
                        max=131072,
                        step=512,
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                # ----- Max message history -----
                vol.Optional(
                    CONF_MAX_MESSAGE_HISTORY,
                    default=defaults.get(CONF_MAX_MESSAGE_HISTORY, DEFAULT_MAX_HISTORY),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0, max=100, step=1, mode=NumberSelectorMode.BOX
                    )
                ),
                # ----- Parallel tool calls -----
                vol.Required(
                    CONF_PARALLEL_TOOL_CALLS,
                    default=defaults.get(CONF_PARALLEL_TOOL_CALLS, True),
                ): BooleanSelector(),
                # ----- Strip emojis from response -----
                vol.Required(
                    CONF_STRIP_EMOJIS,
                    default=defaults.get(CONF_STRIP_EMOJIS, False),
                ): BooleanSelector(),
                # ----- MCP servers -----
                vol.Optional(
                    CONF_MCP_SERVERS,
                    default=defaults.get(CONF_MCP_SERVERS, []),
                ): ObjectSelector(
                    config={
                        "multiple": True,
                        "fields": {
                            "type": {
                                "name": "Type",
                                "required": True,
                                "selector": {
                                    "select": {
                                        "options": MCP_TYPE_OPTIONS,
                                        "mode": "dropdown",
                                    }
                                },
                            },
                            "label": {
                                "name": "Label (ephemeral MCP)",
                                "selector": {"text": None},
                            },
                            "url": {
                                "name": "URL (ephemeral MCP, e.g. https://huggingface.co/mcp)",
                                "selector": {"text": None},
                            },
                            "plugin_id": {
                                "name": "Plugin ID (LM Studio, e.g. mcp/playwright)",
                                "selector": {"text": None},
                            },
                            "allowed_tools": {
                                "name": "Allowed Tools (comma-separated, leave blank for all)",
                                "selector": {"text": None},
                            },
                            "headers": {
                                "name": "Auth Headers (JSON object, e.g. {\"Authorization\":\"Bearer token\"})",
                                "selector": {"text": None},
                            },
                        },
                    }
                ),
            }
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Create a new conversation agent subentry."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Sanitise LLM API list
            if not user_input.get(CONF_LLM_HASS_API):
                user_input.pop(CONF_LLM_HASS_API, None)

            model_name = _strip_model_path(user_input.get(CONF_MODEL, "Agent"))
            return self.async_create_entry(
                title=f"{model_name} – LLM Agent",
                data=user_input,
            )

        return self.async_show_form(
            step_id="user",
            data_schema=await self._build_schema(),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Reconfigure an existing conversation agent subentry."""
        errors: dict[str, str] = {}
        subentry = self._get_reconfigure_subentry()

        if user_input is not None:
            if not user_input.get(CONF_LLM_HASS_API):
                user_input.pop(CONF_LLM_HASS_API, None)

            model_name = _strip_model_path(user_input.get(CONF_MODEL, "Agent"))
            return self.async_update_and_abort(
                self._get_entry(),
                subentry,
                data=user_input,
                title=f"{model_name} – LLM Agent",
            )

        # Filter out APIs that no longer exist
        existing = subentry.data.copy()
        valid_api_ids = {api.id for api in llm.async_get_apis(self.hass)}
        existing[CONF_LLM_HASS_API] = [
            a for a in existing.get(CONF_LLM_HASS_API, []) if a in valid_api_ids
        ]

        schema = self.add_suggested_values_to_schema(
            await self._build_schema(defaults=existing),
            existing,
        )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=schema,
            errors=errors,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _strip_model_path(model_name: str) -> str:
    """Strip file path and .gguf extension from model identifiers (llama.cpp style)."""
    import re
    match = re.search(r"([^/\\]*)\.gguf$", model_name.strip(), re.IGNORECASE)
    return match[1] if match else model_name
