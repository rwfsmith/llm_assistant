# ─────────────────────────────────────────────────────────────────────────────
# Kokoro-FastAPI – ROCm container (AMD GPU / gfx1150 RDNA 3.5 ready)
#
# Self-contained: clones Kokoro-FastAPI source during the build.
# No host-side setup script or pre-cloned source directory needed.
#
# Build args (pass via docker compose build args or --build-arg):
#   ROCM_VERSION   ROCm base image tag, e.g. "7.2"        (default: 7.2)
#   GFX_ARCH       GPU arch for staging wheels, e.g. "gfx1150"  (default: empty)
#   KOKORO_REF     Kokoro-FastAPI branch/tag/SHA           (default: master)
#
# GPU compatibility:
#   RDNA 2 (gfx1030)               ROCm 5.x+   – no GFX_ARCH arg needed
#   RDNA 3 (gfx1100/1101)          ROCm 6.x+   – no GFX_ARCH arg needed
#   RDNA 3.5/Strix Point (gfx1150) ROCm 7.1.1+ – set GFX_ARCH=gfx1150
#   RDNA 4 (gfx1200/1201)          ROCm 7.1.1+ – no GFX_ARCH arg needed
# ─────────────────────────────────────────────────────────────────────────────

ARG ROCM_VERSION=7.2
FROM rocm/dev-ubuntu-24.04:${ROCM_VERSION}-complete

# Re-declare ARGs inside the build stage (they reset after FROM)
ARG ROCM_VERSION=7.2
ARG GFX_ARCH=
ARG KOKORO_REF=master

ENV DEBIAN_FRONTEND=noninteractive \
    ROCM_VERSION=${ROCM_VERSION} \
    PHONEMIZER_ESPEAK_PATH=/usr/bin \
    PHONEMIZER_ESPEAK_DATA=/usr/share/espeak-ng-data \
    ESPEAK_DATA_PATH=/usr/share/espeak-ng-data

# ── System dependencies + uv package manager ──────────────────────────────────
RUN apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends \
        espeak-ng \
        espeak-ng-data \
        rocrand \
        git \
        libsndfile1 \
        curl \
        ffmpeg \
        wget \
        nano \
        g++ \
        zstd \
    && apt-get clean && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /usr/share/espeak-ng-data \
    && ln -sf /usr/lib/*/espeak-ng-data/* /usr/share/espeak-ng-data/ \
    # Install uv
    && curl -LsSf https://astral.sh/uv/install.sh | sh \
    && mv /root/.local/bin/uv /usr/local/bin/ \
    && mv /root/.local/bin/uvx /usr/local/bin/ \
    # Create non-root user
    && useradd -m -u 1001 appuser

# ── Clone Kokoro-FastAPI source ───────────────────────────────────────────────
# Clone to a temp path because /app already exists (created above).
# Move contents in, then ensure the model dir and permissions are set.
ARG KOKORO_REF
RUN git clone --depth 1 --branch ${KOKORO_REF} \
        https://github.com/remsky/Kokoro-FastAPI.git /tmp/kokoro \
    && cp -a /tmp/kokoro/. /app/ \
    && rm -rf /tmp/kokoro \
    && mkdir -p /app/api/src/models/v1_0 \
    && chown -R appuser:appuser /app

USER appuser
WORKDIR /app

# ── Install Python dependencies (ROCm extras) ─────────────────────────────────
# uv respects the Python version in pyproject.toml (.python-version / requires-python).
# Kokoro-FastAPI uses Python 3.10; do not override it.
RUN uv venv && uv sync --extra rocm

# ── gfx1150: install AMD rocm-sdk and configure for Strix Point ───────────────
# The generic ROCm PyTorch wheels have no compiled gfx1150 kernels, causing
# "HIP error: invalid device function" at runtime.  AMD's staging index ships
# a `rocm` Python package (rocm-sdk) that installs gfx1150-native ROCm
# libraries and patches the existing torch installation via `rocm-sdk init`.
# This is architecture-agnostic to the Python version, unlike swapping wheels.
# When GFX_ARCH is not "gfx1150" this step is a no-op.
ARG GFX_ARCH
RUN if [ "${GFX_ARCH}" = "gfx1150" ]; then \
        echo "==> gfx1150: swapping torch/rocm wheels with AMD staging builds..." && \
        uv pip install --no-deps \
            --index-url https://rocm.nightlies.amd.com/v2-staging/gfx1150/ \
            --extra-index-url https://pypi.org/simple \
            torch torchaudio torchvision "rocm[libraries,devel]"; \
    else \
        echo "==> GFX_ARCH=${GFX_ARCH:-unset}: skipping gfx1150 staging step."; \
    fi

# ── MIOpen kernel database (best-effort) ──────────────────────────────────────
# AMD ships pre-built MIOpen kdb files for common GPU architectures via apt.
# Newer GPUs (e.g. gfx1150) have no kdb files yet; failures are non-fatal.
# MIOpen falls back to JIT-compiling kernels at runtime on first inference.
# Set MIOPEN_FIND_MODE=3 + MIOPEN_FIND_ENFORCE=3 in compose to enable the JIT.
RUN cp docker/rocm/kdb_install.sh /tmp/ && \
    ( bash /tmp/kdb_install.sh || \
      echo "WARNING: kdb_install.sh found no kdb files for this arch – MIOpen will JIT-compile at runtime" )

# Note: the upstream "Support older GFX Arch" ROCBlas block (Arch Linux pkg) is
# intentionally omitted. It targets ROCm 6.x / RDNA2 and breaks on ROCm 7.x.

# ── Entrypoint scripts ────────────────────────────────────────────────────────
# Upstream copies docker/scripts/* (entrypoint.sh, download_model.py) into /app.
RUN cp docker/scripts/* . && chmod +x ./entrypoint.sh

# ── Runtime environment ───────────────────────────────────────────────────────
ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app:/app/api \
    PATH="/app/.venv/bin:$PATH" \
    UV_LINK_MODE=copy \
    USE_GPU=true \
    DOWNLOAD_MODEL=true \
    DEVICE=gpu

EXPOSE 8880

CMD ["./entrypoint.sh"]
