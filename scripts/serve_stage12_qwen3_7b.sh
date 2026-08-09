#!/usr/bin/env bash
# 启动步骤一、二使用的本地 Qwen3-7B（vLLM，OpenAI 兼容）。
# 必须显式提供服务器上的权重目录：
#   export STAGE12_LLM_MODEL_PATH=/path/to/Qwen3-7B
#   bash scripts/serve_stage12_qwen3_7b.sh

set -euo pipefail

MODEL_PATH="${STAGE12_LLM_MODEL_PATH:?请先设置 STAGE12_LLM_MODEL_PATH 为 Qwen3-7B 权重目录}"
SERVED_NAME="${STAGE12_LLM_MODEL:-Qwen3-7B}"
HOST="${STAGE12_LLM_HOST:-127.0.0.1}"
PORT="${STAGE12_LLM_PORT:-8001}"
MAX_LEN="${STAGE12_LLM_MAX_MODEL_LEN:-16384}"
GPU_UTIL="${STAGE12_LLM_GPU_MEM_UTIL:-0.85}"
EXTRA_ARGS=("$@")

if [[ ! -d "$MODEL_PATH" ]]; then
  echo "模型目录不存在: $MODEL_PATH" >&2
  exit 1
fi

if [[ -x /home/zyl/miniconda3/envs/approval/bin/vllm ]]; then
  VLLM=/home/zyl/miniconda3/envs/approval/bin/vllm
elif command -v vllm >/dev/null 2>&1; then
  VLLM=vllm
else
  echo "未找到 vllm。请先激活服务器环境并安装 vllm。" >&2
  exit 1
fi

echo "Starting stage1+2 vLLM"
echo "  model path : $MODEL_PATH"
echo "  served name: $SERVED_NAME"
echo "  endpoint   : http://${HOST}:${PORT}/v1"
echo "  max len    : $MAX_LEN"

exec "$VLLM" serve "$MODEL_PATH" \
  --served-model-name "$SERVED_NAME" \
  --host "$HOST" \
  --port "$PORT" \
  --max-model-len "$MAX_LEN" \
  --gpu-memory-utilization "$GPU_UTIL" \
  --trust-remote-code \
  "${EXTRA_ARGS[@]}"
