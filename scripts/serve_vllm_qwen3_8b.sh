#!/usr/bin/env bash
# 启动完整审批流程使用的本地 Qwen3-8B（vLLM，OpenAI 兼容）。
# 必须显式提供服务器上的权重目录：
#   export LLM_MODEL_PATH=/path/to/Qwen3-8B
#   bash scripts/serve_vllm_qwen3_8b.sh

set -euo pipefail

export CUDA_VISIBLE_DEVICES=${LLM_CUDA_VISIBLE_DEVICES:-3}

MODEL_PATH="${LLM_MODEL_PATH:-/home/zyl/LLM Library/Qwen3-8B}"
SERVED_NAME="${LLM_MODEL:-Qwen3-8B}"
HOST="${LLM_HOST:-127.0.0.1}"
PORT="${LLM_PORT:-8001}"
MAX_LEN="${LLM_MAX_MODEL_LEN:-16384}"
GPU_UTIL="${LLM_GPU_MEM_UTIL:-0.9}"
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

echo "Starting vLLM"
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
