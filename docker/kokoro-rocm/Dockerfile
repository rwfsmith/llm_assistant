# ─────────────────────────────────────────────────────────────────────────────
# Kokoro TTS API – ONNX Runtime backend (AMD GPU / CPU)
#
# Both GPU and CPU builds use ubuntu:24.04 as the base image.
# ROCm libraries are installed via the Python rocm-sdk package from AMD's
# gfx1150 staging index — no 10 GB rocm/dev-ubuntu base image needed.
#
# Build args:
#   GPU_SUPPORT    rocm | cpu  (default: rocm)
#
# GPU_SUPPORT=rocm install sequence:
#   1. pip install rocm[libraries,devel]  — downloads and unpacks ROCm libs
#                                           (hipblas, rocblas, etc.) into venv
#   2. python3 -m rocm_sdk init           — extracts the tar, sets up lib paths
#   3. pip install torch                  — gfx1150 native wheels from AMD staging
#   4. pip install onnxruntime-migraphx  — ONNX MIGraphX EP (force-reinstall over
#                                           the CPU onnxruntime from kokoro-onnx)
#
# GPU_SUPPORT=cpu: onnxruntime (CPU) already pulled in by kokoro-onnx deps.
#
# Model files are downloaded at container startup by entrypoint.sh and cached
# in MODEL_DIR (mount a volume for persistence across restarts).
# ─────────────────────────────────────────────────────────────────────────────

ARG GPU_SUPPORT=rocm

FROM ubuntu:24.04

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
# All from AMD gfx1150 staging index so library versions are guaranteed to match.
# rocm-sdk init extracts the bundled ROCm library tar into the venv, making
# hipblas, rocblas etc. available without any system ROCm installation.
ARG GPU_SUPPORT
RUN if [ "${GPU_SUPPORT}" = "rocm" ]; then \
        echo "==> Installing ROCm libs from AMD gfx1150 staging..." && \
        pip install --no-cache-dir \
            --index-url https://rocm.nightlies.amd.com/v2-staging/gfx1150/ \
            "rocm[libraries,devel]" && \
        echo "==> Extracting ROCm libraries via rocm-sdk init..." && \
        python3 -m rocm_sdk init && \
        echo "==> Registering ROCm library path with ldconfig..." && \
        python3 -m rocm_sdk path --root | xargs -I{} sh -c 'echo "{}/lib" > /etc/ld.so.conf.d/rocm.conf' && \
        ldconfig && \
        echo "==> Installing gfx1150 torch from AMD staging (no PyPI fallback)..." && \
        pip install --no-cache-dir \
            --index-url https://rocm.nightlies.amd.com/v2-staging/gfx1150/ \
            torch && \
        echo "==> Installing onnxruntime-migraphx (overwrites CPU onnxruntime)..." && \
        pip install --no-cache-dir --force-reinstall onnxruntime-migraphx; \
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
