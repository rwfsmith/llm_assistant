# ─────────────────────────────────────────────────────────────────────────────
# Kokoro TTS API – ONNX Runtime backend (AMD GPU / CPU)
#
# Build args:
#   ROCM_VERSION   ROCm base image tag  (default: 7.2)  — used when GPU_SUPPORT=rocm
#   GPU_SUPPORT    rocm | cpu           (default: rocm)
#
# GPU_SUPPORT=rocm:
#   base image: rocm/dev-ubuntu-24.04:${ROCM_VERSION}-complete
#   torch:      installed from AMD gfx1150 staging index
#               (https://rocm.nightlies.amd.com/v2-staging/gfx1150/)
#               — provides native gfx1150 kernels; no HSA_OVERRIDE needed
#   onnxruntime: onnxruntime-rocm from PyPI (links against the staged torch)
#
# GPU_SUPPORT=cpu:
#   base image: ubuntu:24.04
#   onnxruntime: standard onnxruntime from PyPI (no torch needed)
#
# Model files are downloaded at container startup by entrypoint.sh and cached
# in MODEL_DIR (mount a named volume for persistence across restarts).
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

# ── PyTorch (ROCm only) + ONNX Runtime ───────────────────────────────────────
# For ROCm / gfx1150:
#   1. Install torch from AMD's gfx1150 staging index — these wheels contain
#      native gfx1150 kernels, so no HSA_OVERRIDE_GFX_VERSION is required.
#   2. Install onnxruntime-rocm from PyPI — it links against the torch ROCm
#      libraries already present on the system/venv from step 1.
# For CPU:
#   Install the standard onnxruntime wheel; no torch dependency needed.
ARG GPU_SUPPORT
RUN if [ "${GPU_SUPPORT}" = "rocm" ]; then \
        echo "==> Installing gfx1150 torch from AMD staging index..." && \
        pip install --no-cache-dir \
            --index-url https://rocm.nightlies.amd.com/v2-staging/gfx1150/ \
            --extra-index-url https://pypi.org/simple \
            torch && \
        echo "==> Installing onnxruntime-rocm..." && \
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
# Note: /opt/venv is intentionally left root-owned — chown-ing several GB of
# torch/onnxruntime wheels takes minutes for no benefit.  Only /app (small)
# needs to be writable by appuser so it can write downloaded models.
RUN useradd -m -u 1001 appuser \
    && mkdir -p /app/models \
    && chown -R appuser:appuser /app

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
