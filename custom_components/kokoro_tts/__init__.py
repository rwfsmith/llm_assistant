"""The Kokoro TTS integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN, LOGGER

PLATFORMS = [Platform.TTS]

type KokoroConfigEntry = ConfigEntry[None]


async def async_setup_entry(hass: HomeAssistant, entry: KokoroConfigEntry) -> bool:
    """Set up Kokoro TTS from a config entry."""
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: KokoroConfigEntry) -> None:
    """Reload on options update."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: KokoroConfigEntry) -> bool:
    """Unload Kokoro TTS."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
