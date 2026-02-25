"""The LLM Assistant integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_KEY, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError, ConfigEntryNotReady
from homeassistant.helpers.httpx_client import get_async_client
from openai import AsyncOpenAI, AuthenticationError, OpenAIError

from .const import CONF_BASE_URL, DOMAIN, LOGGER

PLATFORMS = [Platform.CONVERSATION]

type LLMAssistantConfigEntry = ConfigEntry[AsyncOpenAI]


async def async_setup_entry(hass: HomeAssistant, entry: LLMAssistantConfigEntry) -> bool:
    """Set up LLM Assistant from a config entry."""
    client = AsyncOpenAI(
        base_url=entry.data[CONF_BASE_URL],
        api_key=entry.data.get(CONF_API_KEY) or "not-required",
        http_client=get_async_client(hass),
    )

    try:
        async for _ in client.with_options(timeout=15.0).models.list():
            break
    except AuthenticationError as err:
        LOGGER.error("Invalid API key: %s", err)
        raise ConfigEntryError("Invalid API key") from err
    except OpenAIError as err:
        raise ConfigEntryNotReady(err) from err

    entry.runtime_data = client

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def _async_update_listener(
    hass: HomeAssistant, entry: LLMAssistantConfigEntry
) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: LLMAssistantConfigEntry) -> bool:
    """Unload LLM Assistant."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
