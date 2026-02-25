"""TTS platform for Kokoro TTS integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components import tts
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.httpx_client import get_async_client

from .const import (
    CONF_BASE_URL,
    CONF_LANG_CODE,
    CONF_RESPONSE_FORMAT,
    CONF_SPEED,
    CONF_VOICE,
    DEFAULT_FORMAT,
    DEFAULT_LANG_CODE,
    DEFAULT_SPEED,
    DEFAULT_VOICE,
    DOMAIN,
    LOGGER,
    MAX_SPEED,
    MIN_SPEED,
    OPT_SPEED,
    OPT_VOICE,
)

# Map Kokoro response_format → HA file extension
_FORMAT_TO_EXT: dict[str, str] = {
    "mp3": "mp3",
    "wav": "wav",
    "flac": "flac",
    "opus": "ogg",  # Opus is typically wrapped in an OGG container
    "pcm": "pcm",
}

# Map Kokoro response_format → MIME type (for HA's internal routing)
_FORMAT_TO_MIME: dict[str, str] = {
    "mp3": "audio/mpeg",
    "wav": "audio/wav",
    "flac": "audio/flac",
    "opus": "audio/ogg",
    "pcm": "audio/pcm",
}


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Kokoro TTS from a config entry."""
    async_add_entities([KokoroTTSEntity(config_entry)])


class KokoroTTSEntity(tts.TextToSpeechEntity):
    """Kokoro TTS entity – calls Kokoro-FastAPI /v1/audio/speech."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_should_poll = False

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialise from config entry."""
        self._config_entry = config_entry
        self._attr_unique_id = config_entry.entry_id
        self._attr_device_info = None  # no physical device

    # ------------------------------------------------------------------
    # Language / voice advertising
    # ------------------------------------------------------------------

    @property
    def supported_languages(self) -> list[str]:
        """Return languages that can be generated."""
        # Kokoro supports these BCP-47 codes natively
        return ["en-US", "en-GB", "ja", "zh-CN", "ko", "fr-FR", "de", "es", "pt-BR"]

    @property
    def default_language(self) -> str:
        """Return the default language."""
        return "en-US"

    @property
    def default_options(self) -> dict[str, Any]:
        """Return default options that pre-fill the TTS call."""
        return {
            OPT_VOICE: self._config_entry.data.get(CONF_VOICE, DEFAULT_VOICE),
            OPT_SPEED: self._config_entry.data.get(CONF_SPEED, DEFAULT_SPEED),
        }

    @property
    def supported_options(self) -> list[str]:
        """Options understood by async_get_tts_audio."""
        return [OPT_VOICE, OPT_SPEED]

    async def async_get_voices(
        self, language: str
    ) -> list[tts.Voice] | None:
        """Return available voices – fetched live from the server.

        All Kokoro voices are language-independent from the API perspective;
        the voice's first letter encodes the language (a/b = English, j = Japanese…).
        We return the full list regardless of language so HA can display them.
        """
        base_url = self._config_entry.data[CONF_BASE_URL].rstrip("/")
        url = f"{base_url}/v1/audio/voices"
        try:
            client = get_async_client(self.hass)
            response = await client.get(url, timeout=10.0)
            response.raise_for_status()
            voices: list[str] = response.json().get("voices", [])
            return [tts.Voice(voice_id=v, name=v) for v in sorted(voices)]
        except Exception as err:
            LOGGER.warning("Could not fetch voices: %s", err)
            return None

    # ------------------------------------------------------------------
    # Audio generation
    # ------------------------------------------------------------------

    async def async_get_tts_audio(
        self,
        message: str,
        language: str,
        options: dict[str, Any] | None = None,
    ) -> tts.TtsAudioType:
        """Generate speech audio via Kokoro-FastAPI and return (extension, bytes)."""
        opts = options or {}
        config = self._config_entry.data

        voice: str = opts.get(OPT_VOICE) or config.get(CONF_VOICE, DEFAULT_VOICE)
        speed: float = float(opts.get(OPT_SPEED) or config.get(CONF_SPEED, DEFAULT_SPEED))
        response_format: str = config.get(CONF_RESPONSE_FORMAT, DEFAULT_FORMAT)
        lang_code: str = config.get(CONF_LANG_CODE, DEFAULT_LANG_CODE)

        # Clamp speed to valid range
        speed = max(MIN_SPEED, min(MAX_SPEED, speed))

        base_url = config[CONF_BASE_URL].rstrip("/")
        url = f"{base_url}/v1/audio/speech"

        payload: dict[str, Any] = {
            "model": "kokoro",
            "input": message,
            "voice": voice,
            "speed": speed,
            "response_format": response_format,
            "stream": False,
        }
        if lang_code:
            payload["lang_code"] = lang_code

        LOGGER.debug(
            "Kokoro TTS request: voice=%s speed=%.2f format=%s len=%d chars",
            voice, speed, response_format, len(message),
        )

        try:
            client = get_async_client(self.hass)
            response = await client.post(url, json=payload, timeout=60.0)
            response.raise_for_status()
        except Exception as err:
            LOGGER.error("Kokoro TTS request failed: %s", err)
            return None, None

        ext = _FORMAT_TO_EXT.get(response_format, response_format)
        audio_bytes = response.content

        LOGGER.debug(
            "Kokoro TTS response: %d bytes, format=%s", len(audio_bytes), response_format
        )
        return ext, audio_bytes
