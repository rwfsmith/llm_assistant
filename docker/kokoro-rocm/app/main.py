"""
Minimal Kokoro TTS API – OpenAI-compatible /v1/audio/speech endpoint.

Uses kokoro-onnx for inference — works with CPU (onnxruntime) or AMD GPU
(onnxruntime-rocm) without any PyTorch dependency.

Endpoints:
  GET  /v1/audio/voices          → {"voices": ["af_bella", ...]}
  POST /v1/audio/speech          → WAV / FLAC / PCM audio bytes
  GET  /health                   → {"status": "ok", "model": "...", "provider": "..."}

Environment variables:
  MODEL_DIR      Directory containing model + voices files  (default: /app/models)
  MODEL_VARIANT  fp32 | fp16 | fp16-gpu | int8              (default: fp16)
  ONNX_PROVIDER  Override execution provider                 (default: auto)
  DEFAULT_VOICE  Voice name to use when none is specified    (default: af_bella)
  DEBUG          Set to any value for verbose logging

Model files (downloaded by entrypoint.sh if absent from MODEL_DIR):
  kokoro-v1.0.onnx          fp32  310 MB
  kokoro-v1.0.fp16.onnx     fp16  169 MB  ← default
  kokoro-v1.0.fp16-gpu.onnx fp16  169 MB  (GPU-optimised graph)
  kokoro-v1.0.int8.onnx     int8   88 MB
  voices-v1.0.bin                  27 MB
"""

from __future__ import annotations

import io
import logging
import os
from typing import Annotated, Literal

import numpy as np
import soundfile as sf
from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from kokoro_onnx import Kokoro
from pydantic import BaseModel, Field

logging.basicConfig(
    level=logging.DEBUG if os.getenv("DEBUG") else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
_LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MODEL_DIR = os.getenv("MODEL_DIR", "/app/models")
MODEL_VARIANT = os.getenv("MODEL_VARIANT", "fp16")  # fp32 | fp16 | fp16-gpu | int8
ONNX_PROVIDER = os.getenv("ONNX_PROVIDER", "")  # empty → let kokoro-onnx auto-detect
DEFAULT_VOICE = os.getenv("DEFAULT_VOICE", "af_bella")
SAMPLE_RATE = 24_000

# Map variant name to model filename
_VARIANT_FILES: dict[str, str] = {
    "fp32": "kokoro-v1.0.onnx",
    "fp16": "kokoro-v1.0.fp16.onnx",
    "fp16-gpu": "kokoro-v1.0.fp16-gpu.onnx",
    "int8": "kokoro-v1.0.int8.onnx",
}

_model_file = _VARIANT_FILES.get(MODEL_VARIANT, f"kokoro-v1.0.{MODEL_VARIANT}.onnx")
_model_path = os.path.join(MODEL_DIR, _model_file)
_voices_path = os.path.join(MODEL_DIR, "voices-v1.0.bin")

# ---------------------------------------------------------------------------
# Model initialisation (done once at startup)
# ---------------------------------------------------------------------------
_kokoro: Kokoro | None = None


def _load_model() -> Kokoro:
    """Load the Kokoro ONNX model.  Exported provider can be overridden via env."""
    _LOGGER.info(
        "Loading Kokoro model: variant=%s file=%s", MODEL_VARIANT, _model_path
    )
    if not os.path.exists(_model_path):
        raise RuntimeError(
            f"Model file not found: {_model_path}. "
            "Ensure MODEL_DIR is mounted and entrypoint.sh ran successfully."
        )
    if not os.path.exists(_voices_path):
        raise RuntimeError(
            f"Voices file not found: {_voices_path}. "
            "Ensure MODEL_DIR is mounted and entrypoint.sh ran successfully."
        )

    if ONNX_PROVIDER:
        os.environ.setdefault("ONNX_PROVIDER", ONNX_PROVIDER)

    kokoro = Kokoro(_model_path, _voices_path)
    _LOGGER.info("Kokoro model loaded successfully")
    return kokoro


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(title="Kokoro TTS API", version="1.0.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)


@app.on_event("startup")
async def startup_event() -> None:
    global _kokoro
    import asyncio

    loop = asyncio.get_event_loop()
    _kokoro = await loop.run_in_executor(None, _load_model)
    # Warm-up: one silent synthesis to pre-load any JIT caches
    try:
        _LOGGER.info("Warming up model…")
        await loop.run_in_executor(
            None,
            lambda: _kokoro.create("Hello.", voice=DEFAULT_VOICE, speed=1.0, lang="en-us"),
        )
        _LOGGER.info("Warm-up complete")
    except Exception as exc:
        _LOGGER.warning("Warm-up failed (non-fatal): %s", exc)


def _get_kokoro() -> Kokoro:
    if _kokoro is None:
        raise HTTPException(status_code=503, detail="Model not loaded yet")
    return _kokoro


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------
class SpeechRequest(BaseModel):
    model: str = "kokoro"
    input: str
    voice: str = DEFAULT_VOICE
    speed: Annotated[float, Field(ge=0.5, le=2.0)] = 1.0
    response_format: Literal["wav", "mp3", "flac", "opus", "pcm"] = "wav"
    # Optional language override — kokoro-onnx expects BCP-47 tags like "en-us"
    lang: str = "en-us"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.get("/health")
def health() -> dict:
    provider = os.getenv("ONNX_PROVIDER", "auto")
    return {
        "status": "ok",
        "model_variant": MODEL_VARIANT,
        "model_file": _model_file,
        "provider": provider,
    }


@app.get("/v1/audio/voices")
def list_voices() -> dict:
    """Return available voices."""
    kokoro = _get_kokoro()
    try:
        voices = sorted(kokoro.get_voices())
    except Exception as exc:
        _LOGGER.warning("get_voices() failed, returning empty list: %s", exc)
        voices = []
    return {"voices": voices}


@app.post("/v1/audio/speech")
def synthesize(req: SpeechRequest) -> Response:
    """Synthesize speech and return audio bytes."""
    kokoro = _get_kokoro()

    _LOGGER.debug(
        "Synthesizing: voice=%s lang=%s speed=%.2f format=%s len=%d",
        req.voice,
        req.lang,
        req.speed,
        req.response_format,
        len(req.input),
    )

    try:
        audio_np, sample_rate = kokoro.create(
            req.input, voice=req.voice, speed=req.speed, lang=req.lang
        )
    except Exception as exc:
        _LOGGER.error("Synthesis failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Synthesis failed: {exc}") from exc

    if audio_np is None or len(audio_np) == 0:
        return Response(status_code=204)

    buf = io.BytesIO()
    fmt = req.response_format

    if fmt == "wav":
        sf.write(buf, audio_np, sample_rate, format="WAV", subtype="PCM_16")
        media_type = "audio/wav"
    elif fmt == "flac":
        sf.write(buf, audio_np, sample_rate, format="FLAC")
        media_type = "audio/flac"
    elif fmt == "pcm":
        pcm = (np.clip(audio_np, -1.0, 1.0) * 32767).astype(np.int16)
        buf.write(pcm.tobytes())
        media_type = "audio/pcm"
    else:
        # mp3 / opus not supported by soundfile; fall back to WAV
        _LOGGER.debug("format=%s not natively supported; returning WAV", fmt)
        sf.write(buf, audio_np, sample_rate, format="WAV", subtype="PCM_16")
        media_type = "audio/wav"

    buf.seek(0)
    return Response(content=buf.read(), media_type=media_type)
