"""Constants for the Kokoro TTS integration."""

import logging

DOMAIN = "kokoro_tts"
LOGGER = logging.getLogger(__package__)

# Config keys
CONF_BASE_URL = "base_url"
CONF_VOICE = "voice"
CONF_SPEED = "speed"
CONF_RESPONSE_FORMAT = "response_format"
CONF_LANG_CODE = "lang_code"

# Audio formats supported by Kokoro-FastAPI
AUDIO_FORMATS = ["mp3", "wav", "flac", "opus", "pcm"]
DEFAULT_FORMAT = "mp3"

# Speed range
DEFAULT_SPEED = 1.0
MIN_SPEED = 0.25
MAX_SPEED = 4.0

# Language codes supported by Kokoro
LANG_CODES = {
    "a": "American English",
    "b": "British English",
    "j": "Japanese",
    "z": "Mandarin Chinese",
    "": "Auto-detect",
}
DEFAULT_LANG_CODE = ""

# Well-known default voices (used as fallback if server is unreachable during setup)
DEFAULT_VOICES = [
    "af_bella", "af_heart", "af_jessica", "af_kore", "af_lena",
    "af_nicole", "af_sarah", "af_sky",
    "am_adam", "am_echo", "am_eric", "am_fenrir", "am_liam",
    "am_michael", "am_onyx",
    "bf_alice", "bf_emma", "bf_lily",
    "bm_daniel", "bm_fable", "bm_george", "bm_lewis",
]
DEFAULT_VOICE = "af_bella"

# Option keys exposed on the HA TTS service call
OPT_VOICE = "voice"
OPT_SPEED = "speed"
