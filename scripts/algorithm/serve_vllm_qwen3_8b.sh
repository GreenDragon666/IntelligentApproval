#!/usr/bin/env bash
# 启动完整审批流程使用的本地 Qwen3-8B（vLLM，OpenAI 兼容）。
# 模型、GPU、端口和显存参数统一来自 config/runtime.env。

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$PROJECT_ROOT/scripts/lib/load_runtime_config.sh"
require_runtime_vars LLM_CUDA_VISIBLE_DEVICES LLM_MODEL_PATH LLM_MODEL LLM_HOST LLM_PORT LLM_MAX_MODEL_LEN LLM_GPU_MEM_UTIL LLM_MAX_NUM_SEQS
export CUDA_VISIBLE_DEVICES="$LLM_CUDA_VISIBLE_DEVICES"

EXTRA_ARGS=("$@")

if [[ ! -d "$LLM_MODEL_PATH" ]]; then
  echo "模型目录不存在: $LLM_MODEL_PATH" >&2
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
echo "  config     : $APP_CONFIG_FILE"
echo "  model path : $LLM_MODEL_PATH"
echo "  served name: $LLM_MODEL"
echo "  endpoint   : http://${LLM_HOST}:${LLM_PORT}/v1"
echo "  max len    : $LLM_MAX_MODEL_LEN"
echo "  max seqs   : $LLM_MAX_NUM_SEQS"
echo "  cuda visible: $CUDA_VISIBLE_DEVICES"

exec "$VLLM" serve "$LLM_MODEL_PATH" \
  --served-model-name "$LLM_MODEL" \
  --host "$LLM_HOST" \
  --port "$LLM_PORT" \
  --max-model-len "$LLM_MAX_MODEL_LEN" \
  --gpu-memory-utilization "$LLM_GPU_MEM_UTIL" \
  --max-num-seqs "$LLM_MAX_NUM_SEQS" \
  --enable-prefix-caching \
  --trust-remote-code \
  "${EXTRA_ARGS[@]}"
