#!/usr/bin/env bash

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ENV_FILE:-$REPO_DIR/.env.vlm}"
ENV_NAME="${VLM_ENV_NAME:-odyseus-vlm}"
SERVICE="${VLM_SERVICE_NAME:-vllm}"
SESSION_NAME="${TMUX_SESSION_NAME:-$(basename "$REPO_DIR")-${SERVICE}}"
LOG_DIR="${LOG_DIR:-$HOME/logs/$(basename "$REPO_DIR")}"
LOG_FILE="${LOG_FILE:-$LOG_DIR/${SERVICE}.log}"
REGISTRY="${REGISTRY:-$HOME/odyseus_registry.txt}"
MODEL_NAME="${VLM_MODEL:-Qwen/Qwen3-VL-8B-Instruct}"
HOST="${HOST:-0.0.0.0}"

mkdir -p "$LOG_DIR"

if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

QWEN_URL="${QWEN_URL:-http://127.0.0.1:8012/v1}"
VLLM_PORT="$(printf '%s' "$QWEN_URL" | grep -oE ':[0-9]+' | head -n 1 | tr -d ':')"
VLLM_PORT="${VLLM_PORT:-8012}"
GPU_UTIL_VALUE="${GPU_UTIL:-0.7}"
MAX_MODEL_LEN_VALUE="${MAX_MODEL_LEN:-16384}"

eval "$(conda shell.bash hook)"

if ! conda env list | awk '{print $1}' | grep -qx "$ENV_NAME"; then
  echo "Conda env '$ENV_NAME' does not exist." >&2
  echo "Run ./setup-vlm.sh first, or set VLM_ENV_NAME to an existing env." >&2
  exit 1
fi

tmux kill-session -t "$SESSION_NAME" 2>/dev/null || true
fuser -k "$VLLM_PORT/tcp" 2>/dev/null || true

echo "Launching $SESSION_NAME on port $VLLM_PORT (env: $ENV_NAME, logs: $LOG_FILE)"

tmux new-session -d -s "$SESSION_NAME" "bash -lc '
  source ~/miniconda3/etc/profile.d/conda.sh
  conda activate \"$ENV_NAME\"
  export VLLM_USE_V1=0
  export HF_HOME=\"${HF_HOME:-$HOME/.cache/huggingface}\"
  python -m vllm.entrypoints.openai.api_server \
    --model \"$MODEL_NAME\" \
    --host \"$HOST\" \
    --port \"$VLLM_PORT\" \
    --trust-remote-code \
    --dtype bfloat16 \
    --max-model-len \"$MAX_MODEL_LEN_VALUE\" \
    --gpu-memory-utilization \"$GPU_UTIL_VALUE\" \
    --enforce-eager 2>&1 | tee \"$LOG_FILE\"
'"

touch "$REGISTRY"
sed -i "\|$SESSION_NAME|d" "$REGISTRY" 2>/dev/null || true
echo "$(date '+%Y-%m-%d %H:%M:%S') | $SESSION_NAME | Port: $VLLM_PORT | Log: $LOG_FILE" >> "$REGISTRY"

echo "Session: $SESSION_NAME"
echo "Logs: $LOG_FILE"
echo "Attach with: tmux attach -t $SESSION_NAME"
