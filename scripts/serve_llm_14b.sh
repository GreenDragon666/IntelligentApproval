#!/usr/bin/env bash
# 启动本地 Qwen2.5-Coder-14B-Instruct（资源够时再开）。
# 默认不自动执行。

set -euo pipefail

MODEL_PATH="${LOCAL_LLM_MODEL_PATH:-/home/zyl/public/LLM Library/Qwen2.5-Coder-14B-Instruct}"
SERVED_NAME="${LOCAL_LLM_MODEL:-Qwen2.5-Coder-14B-Instruct}"
HOST="${LOCAL_LLM_HOST:-0.0.0.0}"
PORT="${LOCAL_LLM_PORT:-8000}"
MAX_LEN="${LOCAL_LLM_MAX_MODEL_LEN:-4096}"
GPU_UTIL="${LOCAL_LLM_GPU_MEM_UTIL:-0.90}"

if [[ ! -d "$MODEL_PATH" ]]; then
  echo "模型目录不存在: $MODEL_PATH" >&2
  exit 1
fi

if [[ -x /home/zyl/miniconda3/envs/approval/bin/vllm ]]; then
  VLLM=/home/zyl/miniconda3/envs/approval/bin/vllm
elif command -v vllm >/dev/null 2>&1; then
  VLLM=vllm
else
  echo "未找到 vllm。请先: conda activate approval && pip install vllm" >&2
  exit 1
fi

echo "Starting vLLM 14B at http://127.0.0.1:${PORT}/v1"
exec "$VLLM" serve "$MODEL_PATH" \
  --served-model-name "$SERVED_NAME" \
  --host "$HOST" \
  --port "$PORT" \
  --max-model-len "$MAX_LEN" \
  --gpu-memory-utilization "$GPU_UTIL" \
  --trust-remote-code \
  "$@"
