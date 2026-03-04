# ─────────────────────────────────────────────────────────────────────────────
# Qwen3-ASR API – vLLM backend (AMD GPU / CPU)
#
# Build args:
#   GPU_SUPPORT    rocm | cpu        (default: rocm)
#   ROCM_IMAGE     ROCm base image   (default: rocm/dev-ubuntu-24.04:7.2-complete)
#
# GPU build uses the ROCm base image (system MIGraphX, HIP libs) and installs
# vLLM for ROCm from the AMD gfx1150 staging index on top, along with
# gfx1150-native torch.
#
# GPU_SUPPORT=rocm install sequence:
#   1. apt install migraphx          — system MIGraphX libs (libmigraphx_c.so etc.)
#   2. pip install rocm[libraries,devel]  — gfx1150-tuned ROCm Python libs
#   3. pip install torch             — gfx1150 native wheels from AMD staging
#   4. pip install vllm              — ROCm vLLM from AMD staging
#   5. pip install qwen-asr          — installs without pulling CUDA vllm
#
# GPU_SUPPORT=cpu: uses cpu onnxruntime/transformers backend via qwen-asr.
#
# The model (Qwen/Qwen3-ASR-0.6B) is downloaded by entrypoint.sh on first
# start and cached in MODEL_DIR. Mount a volume for persistence.
# ─────────────────────────────────────────────────────────────────────────────

ARG GPU_SUPPORT=rocm
ARG ROCM_IMAGE=rocm/dev-ubuntu-24.04:7.2-complete

# Named base stages — Docker selects via FROM base-${GPU_SUPPORT}
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
        ffmpeg \
        wget \
        curl \
        ca-certificates \
        git \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# ── Python virtual environment ─────────────────────────────────────────────────
RUN python3.12 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# ── ROCm system libraries (ROCm build only) ───────────────────────────────────
ARG GPU_SUPPORT
RUN if [ "${GPU_SUPPORT}" = "rocm" ]; then \
        echo "==> Installing system MIGraphX libraries via apt..." && \
        apt-get update && apt-get install -y --no-install-recommends migraphx && \
        apt-get clean && rm -rf /var/lib/apt/lists/* && \
        echo "==> Installing gfx1150 ROCm Python libs from AMD staging..." && \
        pip install --no-cache-dir \
            --index-url https://rocm.nightlies.amd.com/v2-staging/gfx1150/ \
            "rocm[libraries,devel]" && \
        echo "==> Installing gfx1150 torch from AMD staging (no PyPI fallback)..." && \
        pip install --no-cache-dir \
            --index-url https://rocm.nightlies.amd.com/v2-staging/gfx1150/ \
            torch && \
        echo "==> Installing ROCm vLLM from AMD staging..." && \
        pip install --no-cache-dir \
            --index-url https://rocm.nightlies.amd.com/v2-staging/gfx1150/ \
            vllm; \
    else \
        echo "==> CPU build: installing torch (CPU)..." && \
        pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu; \
    fi

# ── qwen-asr (installed after vllm to avoid pulling CUDA vllm as a dep) ───────
# Install qwen-asr without the [vllm] extra — vllm is already installed above.
# The vllm backend is selected at runtime via BACKEND env var.
RUN pip install --no-cache-dir \
        "qwen-asr>=0.0.6" \
        "huggingface_hub[cli]>=0.27" \
        "fastapi>=0.115" \
        "uvicorn[standard]>=0.30"

# ── App structure ─────────────────────────────────────────────────────────────
RUN useradd -m -u 1001 appuser \
    && mkdir -p /app/models \
    && chown -R appuser:appuser /app

WORKDIR /app

COPY --chown=appuser:appuser entrypoint.sh ./
RUN sed -i 's/\r$//' /app/entrypoint.sh && chmod +x /app/entrypoint.sh

USER appuser

# ── Runtime environment ───────────────────────────────────────────────────────
ENV MODEL_DIR=/app/models \
    MODEL_NAME=Qwen/Qwen3-ASR-0.6B \
    GPU_MEMORY_UTILIZATION=0.7 \
    MAX_NEW_TOKENS=1024 \
    HOST=0.0.0.0 \
    PORT=8000

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
