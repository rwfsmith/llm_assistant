"""Conversation entity for LLM Assistant."""

from __future__ import annotations

from typing import Literal

from homeassistant.components import conversation
from homeassistant.config_entries import ConfigSubentry
from homeassistant.const import CONF_LLM_HASS_API, CONF_PROMPT, MATCH_ALL
from homeassistant.core import HomeAssistant
from homeassistant.helpers import llm
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import LLMAssistantConfigEntry
from .const import DOMAIN
from .entity import LLMAssistantEntity


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: LLMAssistantConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up conversation entities from a config entry."""
    for subentry_id, subentry in config_entry.subentries.items():
        if subentry.subentry_type != "conversation":
            continue
        async_add_entities(
            [LLMAssistantConversationEntity(config_entry, subentry)],
            config_subentry_id=subentry_id,
        )


class LLMAssistantConversationEntity(
    LLMAssistantEntity, conversation.ConversationEntity
):
    """LLM Assistant conversation agent."""

    _attr_name = None
    _attr_supports_streaming = True

    def __init__(
        self, entry: LLMAssistantConfigEntry, subentry: ConfigSubentry
    ) -> None:
        """Initialize the agent."""
        super().__init__(entry, subentry)
        if self.subentry.data.get(CONF_LLM_HASS_API):
            self._attr_supported_features = (
                conversation.ConversationEntityFeature.CONTROL
            )

    @property
    def supported_languages(self) -> list[str] | Literal["*"]:
        """Return a list of supported languages."""
        return MATCH_ALL

    async def _async_handle_message(
        self,
        user_input: conversation.ConversationInput,
        chat_log: conversation.ChatLog,
    ) -> conversation.ConversationResult:
        """Process the user input and call the API."""
        options = self.subentry.data
        system_prompt = options.get(CONF_PROMPT)

        # Filter HA LLM APIs to only include those that still exist
        available_api_ids = {api.id for api in llm.async_get_apis(self.hass)}
        llm_apis = [
            api_id
            for api_id in options.get(CONF_LLM_HASS_API, [])
            if api_id in available_api_ids
        ]

        try:
            await chat_log.async_provide_llm_data(
                user_input.as_llm_context(DOMAIN),
                llm_apis,
                system_prompt,
                user_input.extra_system_prompt,
            )
        except conversation.ConverseError as err:
            return err.as_conversation_result()

        await self._async_handle_chat_log(chat_log, user_input=user_input)

        return conversation.async_get_result_from_chat_log(user_input, chat_log)
