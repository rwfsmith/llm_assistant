"""TTS platform for Kokoro TTS integration."""

from __future__ import annotations

import re
import struct
from collections.abc import AsyncGenerator
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

# Kokoro PCM output parameters (fixed by the model)
_SAMPLE_RATE = 24_000
_NUM_CHANNELS = 1
_BITS_PER_SAMPLE = 16

# Sentence-end: punctuation followed by whitespace (or end of string).
# The lookbehind keeps the punctuation in the left split-half.
_SENTENCE_END_RE = re.compile(r"(?<=[.!?])(?=\s|$)")
# Minimum characters before a punctuation mark is treated as a sentence boundary.
# Keeps "Dr.", "Mr.", etc. from triggering a split.
_MIN_SENTENCE_CHARS = 20


def _streaming_wav_header(
    sample_rate: int = _SAMPLE_RATE,
    num_channels: int = _NUM_CHANNELS,
    bits_per_sample: int = _BITS_PER_SAMPLE,
) -> bytes:
    """Return a WAV header using 0xFFFFFFFF sentinels for streaming (unknown length)."""
    byte_rate = sample_rate * num_channels * bits_per_sample // 8
    block_align = num_channels * bits_per_sample // 8
    return struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", 0xFFFFFFFF, b"WAVE",
        b"fmt ", 16, 1, num_channels, sample_rate,
        byte_rate, block_align, bits_per_sample,
        b"data", 0xFFFFFFFF,
    )


async def _iter_sentences(message_gen: AsyncGenerator[str]) -> AsyncGenerator[str]:
    """Yield complete sentences from an LLM token async-generator.

    Buffers incoming tokens and flushes whenever a sentence-ending punctuation
    mark (. ! ?) is detected at least _MIN_SENTENCE_CHARS into the buffer.
    Any remaining text is yielded as a final (possibly incomplete) sentence.
    """
    buffer = ""
    async for token in message_gen:
        buffer += token
        # Scan for potential sentence boundaries from left to right.
        while True:
            match = _SENTENCE_END_RE.search(buffer)
            if match is None:
                break
            boundary = match.start()  # index of the char AFTER punctuation
            if boundary < _MIN_SENTENCE_CHARS:
                # Too short — likely an abbreviation; keep scanning after it.
                # Advance past this match to avoid an infinite loop.
                rest = _SENTENCE_END_RE.search(buffer, match.end())
                if rest is None:
                    break
                # Leave the buffer as-is; the next iteration will catch the
                # longer sentence that includes this abbreviation.
                break
            sentence = buffer[:boundary].strip()
            buffer = buffer[match.end():].lstrip()
            if sentence:
                yield sentence
    remainder = buffer.strip()
    if remainder:
        yield remainder


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
        }
        if lang_code:
            payload["lang"] = lang_code

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

    async def async_stream_tts_audio(
        self, request: tts.TTSAudioRequest
    ) -> tts.TTSAudioResponse:
        """Stream speech audio by synthesising each sentence as it arrives from the LLM.

        The pipeline calls this instead of async_get_tts_audio when the
        conversation agent streams its reply token-by-token.  We:
          1. Split the token stream into sentences via _iter_sentences.
          2. POST each sentence to Kokoro with response_format="pcm" and
             stream the raw PCM bytes back.
          3. Wrap the whole sequence in a single streaming WAV header so
             downstream consumers (Wyoming satellite, etc.) see one valid
             WAV stream.
        """
        config = self._config_entry.data
        options = request.options or {}

        voice: str = options.get(OPT_VOICE) or config.get(CONF_VOICE, DEFAULT_VOICE)
        speed: float = float(
            options.get(OPT_SPEED) or config.get(CONF_SPEED, DEFAULT_SPEED)
        )
        lang_code: str = config.get(CONF_LANG_CODE, DEFAULT_LANG_CODE)
        speed = max(MIN_SPEED, min(MAX_SPEED, speed))

        base_url = config[CONF_BASE_URL].rstrip("/")
        url = f"{base_url}/v1/audio/speech"

        async def audio_gen() -> AsyncGenerator[bytes]:
            # One WAV header for the entire response; Kokoro PCM chunks follow.
            yield _streaming_wav_header()

            client = get_async_client(self.hass)
            async for sentence in _iter_sentences(request.message_gen):
                if not sentence:
                    continue

                LOGGER.debug(
                    "Kokoro stream TTS: voice=%s speed=%.2f sentence=%r",
                    voice,
                    speed,
                    sentence[:80],
                )

                payload: dict[str, Any] = {
                    "model": "kokoro",
                    "input": sentence,
                    "voice": voice,
                    "speed": speed,
                    "response_format": "pcm",
                }
                if lang_code:
                    payload["lang"] = lang_code

                try:
                    async with client.stream(
                        "POST", url, json=payload, timeout=30.0
                    ) as resp:
                        resp.raise_for_status()
                        async for chunk in resp.aiter_bytes(4096):
                            if chunk:
                                yield chunk
                except Exception as err:  # noqa: BLE001
                    LOGGER.error(
                        "Kokoro streaming TTS failed for sentence %r: %s",
                        sentence[:40],
                        err,
                    )

        return tts.TTSAudioResponse(extension="wav", data_gen=audio_gen())
