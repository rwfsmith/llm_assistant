# ─────────────────────────────────────────────────────────────────────────────
# Kokoro TTS API – ONNX Runtime backend (AMD GPU / CPU)
#
# Replaces the old PyTorch/Kokoro-FastAPI stack with a clean kokoro-onnx app.
# No PyTorch, no staging wheels, no rocm-sdk — just ONNX Runtime.
#
# Build args:
#   ROCM_VERSION   ROCm base image tag  (default: 7.2)  — used when GPU_SUPPORT=rocm
#   GPU_SUPPORT    rocm | cpu           (default: rocm)
#
# GPU_SUPPORT=rocm  → base: rocm/dev-ubuntu-24.04:${ROCM_VERSION}-complete
#                     pip:  onnxruntime-rocm
#                     env:  ONNX_PROVIDER=ROCMExecutionProvider
# GPU_SUPPORT=cpu   → base: ubuntu:24.04
#                     pip:  onnxruntime
#                     env:  ONNX_PROVIDER=CPUExecutionProvider
#
# Model files are downloaded at container startup by entrypoint.sh and cached
# in MODEL_DIR (mount a named volume for persistence across restarts).
#
# AMD GPU compatibility (gfx1150 / Strix Point):
#   Set HSA_OVERRIDE_GFX_VERSION=11.0.0 in the compose environment so the
#   ROCm/HIP runtime recognises the GPU.  No GFX_ARCH build arg is required.
# ─────────────────────────────────────────────────────────────────────────────

ARG ROCM_VERSION=7.2
ARG GPU_SUPPORT=rocm

# ── Base image aliases (one per GPU_SUPPORT value) ────────────────────────────
FROM rocm/dev-ubuntu-24.04:${ROCM_VERSION}-complete AS base-rocm
FROM ubuntu:24.04 AS base-cpu

# ── Runtime stage – selected by GPU_SUPPORT ───────────────────────────────────
FROM base-${GPU_SUPPORT} AS runtime

ARG GPU_SUPPORT=rocm

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# ── System dependencies ────────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3.12 \
        python3.12-venv \
        python3-pip \
        libsndfile1 \
        wget \
        curl \
        ca-certificates \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# ── Python virtual environment ─────────────────────────────────────────────────
RUN python3.12 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# ── ONNX Runtime – GPU (ROCm) or CPU ─────────────────────────────────────────
# onnxruntime-rocm requires system ROCm libraries (provided by the rocm base
# image).  onnxruntime is the standard CPU-only package.
RUN if [ "${GPU_SUPPORT}" = "rocm" ]; then \
        echo "==> Installing onnxruntime-rocm for AMD GPU..." && \
        pip install --no-cache-dir onnxruntime-rocm; \
    else \
        echo "==> Installing onnxruntime (CPU)..." && \
        pip install --no-cache-dir onnxruntime; \
    fi

# ── Application dependencies ──────────────────────────────────────────────────
RUN pip install --no-cache-dir \
        "fastapi>=0.115" \
        "uvicorn[standard]>=0.30" \
        "kokoro-onnx>=0.5.0" \
        "soundfile>=0.12" \
        "numpy>=1.26"

# ── App structure ─────────────────────────────────────────────────────────────
RUN useradd -m -u 1001 appuser \
    && mkdir -p /app/models \
    && chown -R appuser:appuser /app /opt/venv

WORKDIR /app

COPY --chown=appuser:appuser app/main.py ./
COPY --chown=appuser:appuser entrypoint.sh ./
# Strip Windows CRLF line endings just in case the file was checked out on Windows
RUN sed -i 's/\r$//' /app/entrypoint.sh && chmod +x /app/entrypoint.sh

USER appuser

# ── Runtime environment ───────────────────────────────────────────────────────
ENV MODEL_DIR=/app/models \
    MODEL_VARIANT=fp16 \
    DEFAULT_VOICE=af_bella \
    PYTHONPATH=/app

EXPOSE 8880

ENTRYPOINT ["/app/entrypoint.sh"]
