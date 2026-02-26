# ─────────────────────────────────────────────────────────────────────────────
# Kokoro TTS API – ONNX Runtime backend (AMD GPU / CPU)
#
# Build args:
#   GPU_SUPPORT    rocm | cpu        (default: rocm)
#   ROCM_IMAGE     ROCm base image   (default: rocm/dev-ubuntu-24.04:6.4-complete)
#
# GPU build uses the ROCm base image so that system MIGraphX libraries
# (libmigraphx_c.so etc.) are available for onnxruntime-migraphx.
# rocm[libraries,devel] and torch are still installed from the AMD gfx1150
# staging index on top, to get gfx1150-native library/kernel versions.
#
# GPU_SUPPORT=rocm install sequence:
#   1. pip install rocm[libraries,devel]  — gfx1150-tuned ROCm Python libs
#   2. pip install torch                  — gfx1150 native wheels from AMD staging
#   3. pip install onnxruntime-migraphx   — ONNX MIGraphX EP (replaces CPU onnxruntime)
#
# GPU_SUPPORT=cpu: ubuntu:24.04 base, onnxruntime (CPU) from kokoro-onnx deps.
#
# Model files are downloaded at container startup by entrypoint.sh and cached
# in MODEL_DIR (mount a volume for persistence across restarts).
# ─────────────────────────────────────────────────────────────────────────────

ARG GPU_SUPPORT=rocm
ARG ROCM_IMAGE=rocm/dev-ubuntu-24.04:7.2-complete

# Named base stages — Docker selects via FROM base-${GPU_SUPPORT} below
FROM ubuntu:24.04 AS base-cpu
FROM ${ROCM_IMAGE} AS base-rocm

FROM base-${GPU_SUPPORT}

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

# ── Application dependencies ──────────────────────────────────────────────────
# Install app deps first — kokoro-onnx pulls in plain onnxruntime (CPU) as a
# transitive dep. We overwrite it with onnxruntime-rocm in the ROCm step below.
RUN pip install --no-cache-dir \
        "fastapi>=0.115" \
        "uvicorn[standard]>=0.30" \
        "kokoro-onnx>=0.5.0" \
        "soundfile>=0.12" \
        "numpy>=1.26"

# ── ROCm libraries + PyTorch + ONNX Runtime (ROCm only) ───────────────────────
# System MIGraphX libs come from the ROCm base image (libmigraphx_c.so etc.).
# rocm[libraries,devel] and torch are installed from the gfx1150 staging index
# on top, so gfx1150-native kernels/libs take precedence at runtime.
ARG GPU_SUPPORT
RUN if [ "${GPU_SUPPORT}" = "rocm" ]; then \
        echo "==> Installing gfx1150 ROCm Python libs from AMD staging..." && \
        pip install --no-cache-dir \
            --index-url https://rocm.nightlies.amd.com/v2-staging/gfx1150/ \
            "rocm[libraries,devel]" && \
        echo "==> Installing gfx1150 torch from AMD staging (no PyPI fallback)..." && \
        pip install --no-cache-dir \
            --index-url https://rocm.nightlies.amd.com/v2-staging/gfx1150/ \
            torch && \
        echo "==> Installing onnxruntime-migraphx (replacing CPU onnxruntime)..." && \
        pip uninstall -y onnxruntime onnxruntime-rocm && \
        pip install --no-cache-dir onnxruntime-migraphx; \
    else \
        echo "==> CPU build: onnxruntime already installed via kokoro-onnx deps."; \
    fi

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
