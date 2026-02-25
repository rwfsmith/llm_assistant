#!/usr/bin/env bash
# setup.sh – Clone Kokoro-FastAPI and launch the ROCm container
#
# Run once: bash setup.sh
# Subsequent starts: docker compose up -d
#
# Requirements:
#   - Docker Engine with compose plugin
#   - ROCm-compatible AMD GPU
#   - ROCm drivers installed on the host (https://rocm.docs.amd.com/en/latest/deploy/linux/)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_DIR="$SCRIPT_DIR/src"
KOKORO_REPO="https://github.com/remsky/Kokoro-FastAPI.git"

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
