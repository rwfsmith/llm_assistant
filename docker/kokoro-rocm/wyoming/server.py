"""Wyoming TTS proxy for Kokoro-FastAPI.

Listens on TCP (default port 10200) and translates Wyoming synthesize events
into HTTP requests to a Kokoro-FastAPI instance, then streams the PCM audio
back as Wyoming audio-chunk events.
"""

import argparse
import asyncio
import io
import logging
import wave
from functools import partial
from typing import Optional

import aiohttp
from wyoming.audio import AudioChunk, AudioStart, AudioStop
from wyoming.event import Event
from wyoming.info import Attribution, Info, TtsProgram, TtsVoice
from wyoming.server import AsyncEventHandler, AsyncServer
from wyoming.tts import Synthesize

_LOGGER = logging.getLogger(__name__)

# Number of PCM samples per audio-chunk event
SAMPLES_PER_CHUNK = 1024

# Map Kokoro voice prefix → BCP-47 language tag
_LANG_MAP: dict[str, str] = {
    "af": "en-us",
    "am": "en-us",
    "bf": "en-gb",
    "bm": "en-gb",
    "ef": "es-es",
    "ff": "fr-fr",
    "hf": "hi-in",
    "if": "it-it",
    "jf": "ja-jp",
    "kf": "ko-kr",
    "pf": "pt-br",
    "zf": "zh-cn",
    "zm": "zh-cn",
}


class KokoroWyomingHandler(AsyncEventHandler):
    """Handle Wyoming events for a single client connection."""

    def __init__(
        self,
        wyoming_info: Info,
        kokoro_url: str,
        default_voice: str,
        default_speed: float,
        *args,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.wyoming_info = wyoming_info
        self.kokoro_url = kokoro_url.rstrip("/")
        self.default_voice = default_voice
        self.default_speed = default_speed

    async def handle_event(self, event: Event) -> bool:
        from wyoming.info import Describe

        if Describe.is_type(event.type):
            await self.write_event(self.wyoming_info.event())
            return True

        if not Synthesize.is_type(event.type):
            # Ignore other event types (e.g. synthesize-start for streaming)
            return True

        synthesize = Synthesize.from_event(event)
        voice_name = (
            synthesize.voice.name if synthesize.voice else None
        ) or self.default_voice

        payload = {
            "model": "kokoro",
            "input": synthesize.text,
            "voice": voice_name,
            "speed": self.default_speed,
            "response_format": "wav",  # WAV so we can parse rate/width/channels
        }

        _LOGGER.debug("Synthesizing: voice=%s text=%r", voice_name, synthesize.text[:60])

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.kokoro_url}/v1/audio/speech",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=60),
                ) as resp:
                    resp.raise_for_status()
                    audio_bytes = await resp.read()
        except Exception as exc:
            _LOGGER.error("Kokoro-FastAPI request failed: %s", exc)
            return True

        # Parse WAV header to get audio parameters
        wav_io = io.BytesIO(audio_bytes)
        with wave.open(wav_io, "rb") as wav_file:
            rate = wav_file.getframerate()
            width = wav_file.getsampwidth()
            channels = wav_file.getnchannels()
            pcm_data = wav_file.readframes(wav_file.getnframes())

        _LOGGER.debug(
            "Audio: rate=%d width=%d channels=%d pcm_bytes=%d",
            rate, width, channels, len(pcm_data),
        )

        # Stream PCM as Wyoming audio events
        await self.write_event(
            AudioStart(rate=rate, width=width, channels=channels).event()
        )

        bytes_per_chunk = SAMPLES_PER_CHUNK * width * channels
        offset = 0
        while offset < len(pcm_data):
            chunk = pcm_data[offset : offset + bytes_per_chunk]
            await self.write_event(
                AudioChunk(
                    audio=chunk,
                    rate=rate,
                    width=width,
                    channels=channels,
                ).event()
            )
            offset += bytes_per_chunk

        await self.write_event(AudioStop().event())
        return True


async def fetch_voices(kokoro_url: str, default_voice: str) -> list[TtsVoice]:
    """Fetch available voices from Kokoro-FastAPI and build Wyoming TtsVoice list."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{kokoro_url}/v1/audio/voices",
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                data = await resp.json()
                voice_names: list[str] = data.get("voices", [])
        _LOGGER.info("Fetched %d voices from Kokoro-FastAPI", len(voice_names))
    except Exception as exc:
        _LOGGER.warning(
            "Could not fetch voices from Kokoro-FastAPI (%s); using default: %s",
            exc,
            default_voice,
        )
        voice_names = [default_voice]

    voices: list[TtsVoice] = []
    for name in voice_names:
        prefix = name.split("_")[0] if "_" in name else ""
        lang = _LANG_MAP.get(prefix, "en-us")
        voices.append(
            TtsVoice(
                name=name,
                description=name,
                languages=[lang],
                attribution=Attribution(
                    name="Kokoro",
                    url="https://github.com/remsky/Kokoro-FastAPI",
                ),
                installed=True,
                version=None,
            )
        )
    return voices


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Wyoming TTS proxy for Kokoro-FastAPI"
    )
    parser.add_argument(
        "--kokoro-url",
        default="http://kokoro-tts:8880",
        help="Base URL of the Kokoro-FastAPI service",
    )
    parser.add_argument(
        "--uri",
        default="tcp://0.0.0.0:10200",
        help="Wyoming server URI (e.g. tcp://0.0.0.0:10200)",
    )
    parser.add_argument(
        "--voice",
        default="af_bella",
        help="Default voice name when client does not specify one",
    )
    parser.add_argument(
        "--speed",
        type=float,
        default=1.0,
        help="Playback speed (0.25 – 4.0)",
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    kokoro_url = args.kokoro_url.rstrip("/")

    # Wait for Kokoro-FastAPI to be ready
    _LOGGER.info("Waiting for Kokoro-FastAPI at %s …", kokoro_url)
    for attempt in range(30):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{kokoro_url}/v1/audio/voices",
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    if resp.status == 200:
                        break
        except Exception:
            pass
        await asyncio.sleep(2)
    else:
        _LOGGER.warning("Kokoro-FastAPI not reachable after 60 s; continuing anyway")

    voices = await fetch_voices(kokoro_url, args.voice)

    wyoming_info = Info(
        tts=[
            TtsProgram(
                name="kokoro",
                description="Kokoro TTS via Kokoro-FastAPI (Wyoming proxy)",
                attribution=Attribution(
                    name="Kokoro",
                    url="https://github.com/remsky/Kokoro-FastAPI",
                ),
                installed=True,
                voices=voices,
                version="1.0.0",
            )
        ]
    )

    server = AsyncServer.from_uri(args.uri)
    _LOGGER.info(
        "Wyoming Kokoro proxy ready  uri=%s  backend=%s  default_voice=%s",
        args.uri,
        kokoro_url,
        args.voice,
    )

    await server.run(
        partial(
            KokoroWyomingHandler,
            wyoming_info,
            kokoro_url,
            args.voice,
            args.speed,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
