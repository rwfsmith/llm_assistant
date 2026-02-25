#!/usr/bin/env bash
# entrypoint.sh – Download Kokoro ONNX model files if absent, then start the API.
#
# Environment variables (can be overridden via compose):
#   MODEL_DIR      Local directory for model + voices files  (default: /app/models)
#   MODEL_VARIANT  fp32 | fp16 | fp16-gpu | int8             (default: fp16)
#
# Downloads from the kokoro-onnx GitHub releases (model-files-v1.0 tag).
set -euo pipefail

BASE_URL="https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
MODEL_DIR="${MODEL_DIR:-/app/models}"
MODEL_VARIANT="${MODEL_VARIANT:-fp16}"

# Map variant → filename
declare -A VARIANT_FILES=(
    ["fp32"]="kokoro-v1.0.onnx"
    ["fp16"]="kokoro-v1.0.fp16.onnx"
    ["fp16-gpu"]="kokoro-v1.0.fp16-gpu.onnx"
    ["int8"]="kokoro-v1.0.int8.onnx"
)

MODEL_FILE="${VARIANT_FILES[$MODEL_VARIANT]:-kokoro-v1.0.fp16.onnx}"
VOICES_FILE="voices-v1.0.bin"

mkdir -p "${MODEL_DIR}"

download_if_missing() {
    local file="$1"
    local url="$2"
    local dest="${MODEL_DIR}/${file}"

    if [ -f "${dest}" ]; then
        echo "==> Found: ${dest}"
    else
        echo "==> Downloading ${file} ..."
        wget --no-verbose --show-progress -O "${dest}" "${url}" \
            || { echo "ERROR: Failed to download ${url}"; exit 1; }
        echo "==> Downloaded: ${dest}"
    fi
}

download_if_missing "${MODEL_FILE}" "${BASE_URL}/${MODEL_FILE}"
download_if_missing "${VOICES_FILE}" "${BASE_URL}/${VOICES_FILE}"

echo "==> Model ready: ${MODEL_DIR}/${MODEL_FILE}"
echo "==> Starting Kokoro TTS API on :8880 ..."

exec python3 -m uvicorn main:app --host 0.0.0.0 --port 8880
