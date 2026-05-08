#!/usr/bin/env bash

set -euo pipefail

ENV_NAME="${CONDA_ENV_NAME:-spatial-vlm}"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8080}"
MODEL_DIR="${DA3_MODEL_DIR:-depth-anything/DA3METRIC-LARGE}"
PROCESS_RES="${PROCESS_RES:-504}"

eval "$(conda shell.bash hook)"
conda activate "${ENV_NAME}"

python demo.py \
  --host "${HOST}" \
  --port "${PORT}" \
  --model-dir "${MODEL_DIR}" \
  --process-res "${PROCESS_RES}"
