#!/usr/bin/env bash
# 校验统一配置的必填项、类型和服务器文件路径，不启动任何服务。

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$PROJECT_ROOT/scripts/lib/load_runtime_config.sh"
require_backend_runtime_vars
require_algorithm_runtime_vars
require_runtime_vars LLM_CUDA_VISIBLE_DEVICES LLM_MODEL_PATH LLM_MODEL LLM_HOST LLM_PORT LLM_MAX_MODEL_LEN LLM_GPU_MEM_UTIL LLM_MAX_NUM_SEQS VITE_REVIEW_API_URL

PYTHONPATH="$PROJECT_ROOT/backend${PYTHONPATH:+:$PYTHONPATH}" python -c 'from app.config import Settings; Settings()'

FAILED=0
if [[ ! -d "$ALGORITHM_ROOT" ]]; then
  echo "算法目录不存在: $ALGORITHM_ROOT" >&2
  FAILED=1
fi
if runtime_bool_is_true "$ALGORITHM_USE_LLM_MATCHING" || runtime_bool_is_true "$ALGORITHM_ENABLE_LLM_CHECK" || runtime_bool_is_true "$ALGORITHM_LLM_REVIEW"; then
  if [[ ! -d "$LLM_MODEL_PATH" ]]; then
    echo "vLLM 模型目录不存在: $LLM_MODEL_PATH" >&2
    FAILED=1
  fi
fi
if runtime_bool_is_true "$ALGORITHM_USE_EMBEDDING" && [[ ! -d "$LOCAL_EMBED_MODEL" ]]; then
  echo "embedding 模型目录不存在: $LOCAL_EMBED_MODEL" >&2
  FAILED=1
fi
if [[ ! -f "$POLICY_RULES_PATH" ]]; then
  echo "政策规则文件不存在: $POLICY_RULES_PATH" >&2
  FAILED=1
fi
if [[ "$FAILED" -ne 0 ]]; then
  exit 1
fi

echo "统一配置校验通过: $APP_CONFIG_FILE"
echo "  后端: http://127.0.0.1:${BACKEND_PORT}${API_PREFIX}"
echo "  vLLM: http://${LLM_HOST}:${LLM_PORT}/v1，GPU ${LLM_CUDA_VISIBLE_DEVICES}"
echo "  规则: $POLICY_RULES_PATH"
echo "  存储: $STORAGE_ROOT"
