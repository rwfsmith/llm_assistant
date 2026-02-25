#!/usr/bin/env bash
# setup.sh – Clone Kokoro-FastAPI and launch the ROCm container
#
# Run once: bash setup.sh
# Subsequent starts: docker compose up -d
#
# Requirements:
#   - Docker Engine with compose plugin
#   - ROCm-compatible AMD GPU accessible via /dev/kfd
#
# GPU compatibility:
#   RDNA 2 (gfx1030)          ROCm 5.x+
#   RDNA 3 (gfx1100/1101)     ROCm 6.x+
#   RDNA 3.5/4 / Strix Point  ROCm 7.1.1+  (gfx1150, Ryzen AI 9 HX 370, etc.)
#   CDNA (Instinct)            ROCm 5.x+
#
# Override the ROCm version before running:
#   ROCM_VERSION=7.2.0 bash setup.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_DIR="$SCRIPT_DIR/src"
KOKORO_REPO="https://github.com/remsky/Kokoro-FastAPI.git"

# ROCm version baked into the container image.
# 7.2.0 is required for gfx1150 (Strix Point / Ryzen AI 9 HX 370) and RDNA 4.
# Set to 6.4.4 for older RDNA 2/3 cards if you have image pull issues.
ROCM_VERSION="${ROCM_VERSION:-7.2.0}"
# Short form used in PyTorch wheel URLs (e.g. "7.2" from "7.2.0")
ROCM_SHORT="$(echo "$ROCM_VERSION" | cut -d. -f1-2)"

# ---------------------------------------------------------------------------
# 1. Clone / update Kokoro-FastAPI source
# ---------------------------------------------------------------------------
if [ -d "$SRC_DIR/.git" ]; then
    echo "==> Updating Kokoro-FastAPI source..."
    git -C "$SRC_DIR" pull --ff-only
else
    echo "==> Cloning Kokoro-FastAPI..."
    git clone --depth 1 "$KOKORO_REPO" "$SRC_DIR"
fi

# ---------------------------------------------------------------------------
# 1b. Patch Kokoro-FastAPI's ROCm Dockerfile to use the requested ROCm version
# ---------------------------------------------------------------------------
ROCM_DOCKERFILE="$SRC_DIR/docker/rocm/Dockerfile"
if [ -f "$ROCM_DOCKERFILE" ]; then
    echo "==> Patching ROCm Dockerfile: base image → rocm/dev-ubuntu-24.04:${ROCM_VERSION}-complete"
    # Replace the FROM base image (any rocm/dev-ubuntu-* tag)
    sed -i -E \
        "s|FROM rocm/dev-ubuntu-[^:]+:[^[:space:]]+|FROM rocm/dev-ubuntu-24.04:${ROCM_VERSION}-complete|g" \
        "$ROCM_DOCKERFILE"

    # Replace the PyTorch ROCm wheel URL (e.g. rocm6.4 → rocm7.2)
    # PyTorch publishes wheels at https://download.pytorch.org/whl/rocmX.Y
    sed -i -E \
        "s|rocm[0-9]+\\.[0-9]+(\\.[0-9]+)?|rocm${ROCM_SHORT}|g" \
        "$ROCM_DOCKERFILE"

    echo "==> Dockerfile patched (ROCm ${ROCM_VERSION}, PyTorch wheel rocm${ROCM_SHORT})"
else
    echo "==> Warning: $ROCM_DOCKERFILE not found – skipping patch"
fi

# ---------------------------------------------------------------------------
# 2. Detect render/video group IDs for GPU passthrough (Linux)
# ---------------------------------------------------------------------------
VIDEO_GID=$(getent group video  2>/dev/null | cut -d: -f3 || echo 44)
RENDER_GID=$(getent group render 2>/dev/null | cut -d: -f3 || echo 109)

echo "==> Using video GID=$VIDEO_GID  render GID=$RENDER_GID"

# Export so docker-compose.yml can use them
export VIDEO_GID RENDER_GID

# ---------------------------------------------------------------------------
# 3. Create persistent directories
# ---------------------------------------------------------------------------
mkdir -p "$SCRIPT_DIR/data/models"
mkdir -p "$SCRIPT_DIR/data/miopen-config"
mkdir -p "$SCRIPT_DIR/data/miopen-cache"

# ---------------------------------------------------------------------------
# 4. Start the container
# ---------------------------------------------------------------------------
echo "==> Building and starting Kokoro-FastAPI (ROCm)..."
cd "$SCRIPT_DIR"
docker compose up -d --build

echo ""
echo "==> Kokoro-FastAPI is starting up on http://localhost:8880"
echo "    API docs:  http://localhost:8880/docs"
echo "    Web UI:    http://localhost:8880/web"
echo ""
echo "    The model will be downloaded on first start (~326 MB)."
echo "    Stream logs:  docker compose logs -f kokoro-tts"
echo ""
echo "    Home Assistant integration URL: http://<HOST_IP>:8880"
