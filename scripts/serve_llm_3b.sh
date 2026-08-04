#!/usr/bin/env bash
# 启动本地 Qwen2.5-Coder-3B-Instruct（vLLM，OpenAI 兼容）。
# 本脚本只负责起服务；默认请你手动执行，仓库流程不会自动调用。
#
# 依赖：conda 环境 approval 中已安装 vllm
#   /home/zyl/miniconda3/envs/approval/bin/pip install vllm
#
# 用法：
#   bash scripts/serve_llm_3b.sh
#   bash scripts/serve_llm_3b.sh --port 8000 --max-model-len 4096

set -euo pipefail

MODEL_PATH="${LOCAL_LLM_MODEL_PATH:-/home/zyl/public/LLM Library/Qwen2.5-Coder-3B-Instruct}"
SERVED_NAME="${LOCAL_LLM_MODEL:-Qwen2.5-Coder-3B-Instruct}"
HOST="${LOCAL_LLM_HOST:-0.0.0.0}"
PORT="${LOCAL_LLM_PORT:-8000}"
MAX_LEN="${LOCAL_LLM_MAX_MODEL_LEN:-4096}"
GPU_UTIL="${LOCAL_LLM_GPU_MEM_UTIL:-0.85}"

# 允许把额外参数透传给 vllm（写在脚本参数里）
EXTRA_ARGS=("$@")

if [[ ! -d "$MODEL_PATH" ]]; then
  echo "模型目录不存在: $MODEL_PATH" >&2
  exit 1
fi

# 优先用 approval 环境的 vllm
if [[ -x /home/zyl/miniconda3/envs/approval/bin/vllm ]]; then
  VLLM=/home/zyl/miniconda3/envs/approval/bin/vllm
elif command -v vllm >/dev/null 2>&1; then
  VLLM=vllm
else
  echo "未找到 vllm。请先: conda activate approval && pip install vllm" >&2
  exit 1
fi

echo "Starting vLLM"
echo "  model path : $MODEL_PATH"
echo "  served name: $SERVED_NAME"
echo "  endpoint   : http://127.0.0.1:${PORT}/v1"
echo "  max len    : $MAX_LEN"

exec "$VLLM" serve "$MODEL_PATH" \
  --served-model-name "$SERVED_NAME" \
  --host "$HOST" \
  --port "$PORT" \
  --max-model-len "$MAX_LEN" \
  --gpu-memory-utilization "$GPU_UTIL" \
  --trust-remote-code \
  "${EXTRA_ARGS[@]}"
