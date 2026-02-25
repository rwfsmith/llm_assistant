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
# Short form used in PyTorch wheel URLs and ROCm 7.x image tags (e.g. "7.2" from "7.2.0")
ROCM_SHORT="$(echo "$ROCM_VERSION" | cut -d. -f1-2)"
ROCM_MAJOR="$(echo "$ROCM_VERSION" | cut -d. -f1)"

# ROCm 6.x tags: X.Y.Z-complete  (e.g. 6.4.4-complete)
# ROCm 7.x tags: X.Y-complete    (e.g. 7.2-complete)
if [ "$ROCM_MAJOR" -ge 7 ]; then
    ROCM_IMAGE_TAG="${ROCM_SHORT}-complete"
else
    ROCM_IMAGE_TAG="${ROCM_VERSION}-complete"
fi

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
    echo "==> Patching ROCm Dockerfile for ROCm ${ROCM_VERSION} (image tag: ${ROCM_IMAGE_TAG})"

    # 1. Replace FROM base image (any rocm/dev-ubuntu-* tag)
    sed -i -E \
        "s|FROM rocm/dev-ubuntu-[^:]+:[^[:space:]]+|FROM rocm/dev-ubuntu-24.04:${ROCM_IMAGE_TAG}|g" \
        "$ROCM_DOCKERFILE"

    # 2. Replace the ENV ROCM_VERSION line used by kdb_install.sh
    #    (format in Dockerfile: ENV ROCM_VERSION=X.Y.Z)
    sed -i -E \
        "s|ENV ROCM_VERSION=[0-9]+\.[0-9]+(\.[0-9]+)?|ENV ROCM_VERSION=${ROCM_SHORT}|g" \
        "$ROCM_DOCKERFILE"

    # 3. Replace PyTorch ROCm wheel index URL (e.g. rocm6.4 → rocm7.2)
    #    Only match the wheel URL pattern (preceded by / or = to avoid matching rocm/ image names)
    sed -i -E \
        "s|(download\.pytorch\.org/whl/)rocm[0-9]+\.[0-9]+|\1rocm${ROCM_SHORT}|g" \
        "$ROCM_DOCKERFILE"

    # 4. Remove the "Support older GFX Arch" ROCBlas override block for ROCm 7.x.
    #    That step downloads a ROCm 6.x Arch Linux package and breaks on 7.x / gfx1150.
    #    It exists only to broaden RDNA2 compat; newer GPUs don't need it.
    if [ "$ROCM_MAJOR" -ge 7 ]; then
        echo "==> Removing legacy ROCBlas override (not needed for ROCm 7.x / gfx1150)"
        python3 - "$ROCM_DOCKERFILE" <<'PYEOF'
import sys, re
path = sys.argv[1]
text = open(path).read()
# Remove the ENV ROCBLAS_VERSION + RUN block that downloads the archlinux rocblas package
text = re.sub(
    r'#\s*Support older GFX Arch\s*\n'
    r'ENV ROCBLAS_VERSION=.*?\n'
    r'RUN cd /tmp.*?rocblas/\n',
    '# (ROCBlas override removed – not needed for ROCm 7.x / gfx1150)\n',
    text, flags=re.DOTALL
)
open(path, 'w').write(text)
print("  ROCBlas override block removed.")
PYEOF
    fi

    # 5. Inject GFX_ARCH so kdb_install.sh picks the right kernel shape files.
    #    The Dockerfile has no ARG for this; inject an ENV before the kdb_install step.
    GFX_ARCH="${GFX_ARCH:-}"
    if [ -n "$GFX_ARCH" ]; then
        echo "==> Injecting ENV GFX_ARCH=${GFX_ARCH} into Dockerfile"
        sed -i \
            "s|COPY --chown=appuser:appuser docker/rocm/kdb_install.sh /tmp/|ENV GFX_ARCH=${GFX_ARCH}\nCOPY --chown=appuser:appuser docker/rocm/kdb_install.sh /tmp/|" \
            "$ROCM_DOCKERFILE"
    else
        echo "==> Note: GFX_ARCH not set; kdb_install.sh will use its default architecture list."
        echo "    For gfx1150 (Ryzen AI 9 HX 370): export GFX_ARCH=gfx1150 && bash setup.sh"
    fi

    echo "==> Dockerfile patched (image tag ${ROCM_IMAGE_TAG}, ROCM_VERSION=${ROCM_SHORT})"

    # 6. Patch kdb_install.sh to warn instead of exit 1 when no kdb files exist.
    #    gfx1150 and other newer GPUs don't have pre-built MIOpen kernel shape files
    #    in AMD's apt repo yet. Without this, the Docker build fails. MIOpen will
    #    JIT-compile the kernels at runtime on first use instead (slower first request,
    #    but otherwise fully functional).
    KDB_INSTALL="$SRC_DIR/docker/rocm/kdb_install.sh"
    if [ -f "$KDB_INSTALL" ]; then
        echo "==> Patching kdb_install.sh: missing kdb files → warning (not fatal error)"
        python3 - "$KDB_INSTALL" <<'PYEOF'
import sys, re
path = sys.argv[1]
text = open(path).read()
# 1. Make "No MIOpen kdb files found" non-fatal (both Ubuntu and RHEL variants).
text = re.sub(
    r'(echo\s+-e\s+"ERROR: No MIOpen kernel database files found[^"]*")\s*\n(\s*)exit 1',
    r'\1\n\2echo "WARNING: No kdb files for this arch in AMD repo; MIOpen will JIT-compile at runtime."\n\2continue',
    text
)
# 2. Make the final cp conditional so it doesn't fail when no kdb files were downloaded.
text = text.replace(
    'cp -ra opt/rocm-*/share/miopen $TORCH_INSTALL_PATH/torch/share',
    'if ls opt/rocm-*/share/miopen 2>/dev/null | head -1 | grep -q .; then\n    cp -ra opt/rocm-*/share/miopen $TORCH_INSTALL_PATH/torch/share\nelse\n    echo "No kdb files to copy; MIOpen will JIT-compile kernels at runtime."\nfi'
)
open(path, 'w').write(text)
print("  kdb_install.sh patched.")
PYEOF
    fi
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
