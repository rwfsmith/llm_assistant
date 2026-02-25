"""Config flow for Kokoro TTS integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.httpx_client import get_async_client
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import (
    AUDIO_FORMATS,
    CONF_BASE_URL,
    CONF_LANG_CODE,
    CONF_RESPONSE_FORMAT,
    CONF_SPEED,
    CONF_VOICE,
    DEFAULT_FORMAT,
    DEFAULT_LANG_CODE,
    DEFAULT_SPEED,
    DEFAULT_VOICE,
    DEFAULT_VOICES,
    DOMAIN,
    LANG_CODES,
    LOGGER,
    MAX_SPEED,
    MIN_SPEED,
)


async def _fetch_voices(hass, base_url: str) -> list[str]:
    """Fetch the voice list from the Kokoro server."""
    url = base_url.rstrip("/") + "/v1/audio/voices"
    try:
        client = get_async_client(hass)
        response = await client.get(url, timeout=10.0)
        response.raise_for_status()
        data = response.json()
        voices: list[str] = data.get("voices", [])
        return sorted(voices) if voices else DEFAULT_VOICES
    except Exception as err:
        LOGGER.warning("Could not fetch voices from %s: %s – using defaults", url, err)
        return DEFAULT_VOICES


async def _test_connectivity(hass, base_url: str) -> bool:
    """Verify the server responds to a voices request."""
    url = base_url.rstrip("/") + "/v1/audio/voices"
    try:
        client = get_async_client(hass)
        response = await client.get(url, timeout=10.0)
        return response.status_code < 500
    except Exception as err:
        LOGGER.debug("Connectivity test failed for %s: %s", base_url, err)
        return False


class KokoroTTSConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Kokoro TTS."""

    VERSION = 1

    def __init__(self) -> None:
        self._base_url: str = ""
        self._voices: list[str] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 1 – ask for the server URL and test connectivity."""
        errors: dict[str, str] = {}

        if user_input is not None:
            base_url = user_input[CONF_BASE_URL].rstrip("/")
            ok = await _test_connectivity(self.hass, base_url)
            if not ok:
                errors["base"] = "cannot_connect"
            else:
                self._base_url = base_url
                self._voices = await _fetch_voices(self.hass, base_url)
                return await self.async_step_voice()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_BASE_URL,
                        default="http://localhost:8880",
                    ): str,
                }
            ),
            errors=errors,
        )

    async def async_step_voice(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 2 – choose voice, speed, format, language."""
        if user_input is not None:
            return self.async_create_entry(
                title=f"Kokoro TTS ({self._base_url})",
                data={
                    CONF_BASE_URL: self._base_url,
                    **user_input,
                },
            )

        voice_options = [
            SelectOptionDict(label=v, value=v) for v in self._voices
        ]
        default_voice = DEFAULT_VOICE if DEFAULT_VOICE in self._voices else self._voices[0]

        lang_options = [
            SelectOptionDict(label=label, value=code)
            for code, label in LANG_CODES.items()
        ]
        format_options = [
            SelectOptionDict(label=fmt.upper(), value=fmt) for fmt in AUDIO_FORMATS
        ]

        return self.async_show_form(
            step_id="voice",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_VOICE, default=default_voice): SelectSelector(
                        SelectSelectorConfig(
                            options=voice_options,
                            mode=SelectSelectorMode.DROPDOWN,
                            custom_value=True,
                        )
                    ),
                    vol.Required(CONF_SPEED, default=DEFAULT_SPEED): NumberSelector(
                        NumberSelectorConfig(
                            min=MIN_SPEED,
                            max=MAX_SPEED,
                            step=0.05,
                            mode=NumberSelectorMode.SLIDER,
                        )
                    ),
                    vol.Required(
                        CONF_RESPONSE_FORMAT, default=DEFAULT_FORMAT
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=format_options,
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Optional(
                        CONF_LANG_CODE, default=DEFAULT_LANG_CODE
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=lang_options,
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
            ),
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Allow reconfiguration."""
        errors: dict[str, str] = {}
        entry = self._get_reconfigure_entry()

        if user_input is not None:
            base_url = user_input.get(CONF_BASE_URL, entry.data[CONF_BASE_URL]).rstrip("/")
            ok = await _test_connectivity(self.hass, base_url)
            if not ok:
                errors["base"] = "cannot_connect"
            else:
                voices = await _fetch_voices(self.hass, base_url)
                voice_options = [SelectOptionDict(label=v, value=v) for v in voices]
                # If the URL itself changed, ask voice step again; otherwise just save
                return self.async_update_reload_and_abort(
                    entry=entry,
                    title=f"Kokoro TTS ({base_url})",
                    data={**entry.data, **user_input, CONF_BASE_URL: base_url},
                )

        existing = entry.data.copy()
        self._base_url = existing.get(CONF_BASE_URL, "http://localhost:8880")
        self._voices = await _fetch_voices(self.hass, self._base_url)
        voice_options = [SelectOptionDict(label=v, value=v) for v in self._voices]
        lang_options = [
            SelectOptionDict(label=label, value=code) for code, label in LANG_CODES.items()
        ]
        format_options = [
            SelectOptionDict(label=fmt.upper(), value=fmt) for fmt in AUDIO_FORMATS
        ]

        schema = self.add_suggested_values_to_schema(
            vol.Schema(
                {
                    vol.Required(CONF_BASE_URL): str,
                    vol.Required(CONF_VOICE): SelectSelector(
                        SelectSelectorConfig(
                            options=voice_options,
                            mode=SelectSelectorMode.DROPDOWN,
                            custom_value=True,
                        )
                    ),
                    vol.Required(CONF_SPEED): NumberSelector(
                        NumberSelectorConfig(
                            min=MIN_SPEED, max=MAX_SPEED, step=0.05,
                            mode=NumberSelectorMode.SLIDER,
                        )
                    ),
                    vol.Required(CONF_RESPONSE_FORMAT): SelectSelector(
                        SelectSelectorConfig(options=format_options, mode=SelectSelectorMode.DROPDOWN)
                    ),
                    vol.Optional(CONF_LANG_CODE): SelectSelector(
                        SelectSelectorConfig(options=lang_options, mode=SelectSelectorMode.DROPDOWN)
                    ),
                }
            ),
            existing,
        )

        return self.async_show_form(
            step_id="reconfigure", data_schema=schema, errors=errors
        )
