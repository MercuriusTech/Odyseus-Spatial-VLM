#!/usr/bin/env bash

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_NAME="${1:-${VLM_ENV_NAME:-odyseus-vlm}}"
PYTHON_VERSION="${PYTHON_VERSION:-3.10}"
TORCH_INDEX_URL="${TORCH_INDEX_URL:-https://download.pytorch.org/whl/cu121}"
TORCH_VERSION="${TORCH_VERSION:-2.5.1}"
TORCHVISION_VERSION="${TORCHVISION_VERSION:-0.20.1}"
VLLM_VERSION="${VLLM_VERSION:-0.8.5}"
ENV_FILE="${ENV_FILE:-$REPO_DIR/.env.vlm}"

eval "$(conda shell.bash hook)"

if ! conda env list | awk '{print $1}' | grep -qx "$ENV_NAME"; then
  conda create -y -n "$ENV_NAME" "python=${PYTHON_VERSION}"
fi

conda activate "$ENV_NAME"

python -m pip install --upgrade pip setuptools wheel
python -m pip install --index-url "$TORCH_INDEX_URL" \
  "torch==${TORCH_VERSION}" \
  "torchvision==${TORCHVISION_VERSION}"
python -m pip install "vllm==${VLLM_VERSION}"

if [ ! -f "$ENV_FILE" ]; then
  cat > "$ENV_FILE" <<'EOF'
QWEN_URL=http://127.0.0.1:8012/v1
GPU_UTIL=0.7
MAX_MODEL_LEN=16384
VLM_MODEL=Qwen/Qwen3-VL-8B-Instruct
VLM_ENV_NAME=odyseus-vlm
EOF
fi

cat <<EOF

VLM environment ready.

Env name:
  $ENV_NAME

Config file:
  $ENV_FILE

Start the server with:
  ./run-vlm.sh
EOF
