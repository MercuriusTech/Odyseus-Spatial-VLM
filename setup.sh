#!/usr/bin/env bash

set -euo pipefail

ENV_NAME="${1:-spatial-vlm}"
PYTHON_VERSION="${PYTHON_VERSION:-3.10}"
CONDA_CHANNEL_ARGS=(
  --override-channels
  -c conda-forge
)
TORCH_INDEX_URL="${TORCH_INDEX_URL:-https://download.pytorch.org/whl/cu121}"
TORCH_VERSION="${TORCH_VERSION:-2.5.1}"
TORCHVISION_VERSION="${TORCHVISION_VERSION:-0.20.1}"

eval "$(conda shell.bash hook)"
conda config --set channel_priority strict >/dev/null

if ! conda env list | awk '{print $1}' | grep -qx "${ENV_NAME}"; then
  conda create -y "${CONDA_CHANNEL_ARGS[@]}" -n "${ENV_NAME}" "python=${PYTHON_VERSION}"
fi

conda activate "${ENV_NAME}"

pip install --upgrade pip
pip install --index-url "${TORCH_INDEX_URL}" \
  "torch==${TORCH_VERSION}" \
  "torchvision==${TORCHVISION_VERSION}"
pip install \
  xformers \
  fastapi \
  "uvicorn[standard]" \
  python-multipart \
  pillow \
  "numpy<2" \
  opencv-python \
  huggingface_hub \
  einops \
  omegaconf \
  safetensors \
  imageio \
  addict \
  tqdm \
  evo \
  "moviepy==1.0.3" \
  plyfile \
  trimesh \
  requests

pip install --no-deps -e ./Depth-Anything-3

cat <<EOF

Environment ready.

Activate it with:
  conda activate ${ENV_NAME}

Then start the demo:
  ./run.sh

The model weights will be downloaded on first launch unless DA3_MODEL_DIR points to a local checkpoint or cache.
EOF
