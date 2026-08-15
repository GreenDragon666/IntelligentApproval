#!/usr/bin/env bash
# 使用统一配置检查 vLLM 的 OpenAI 兼容接口。

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$PROJECT_ROOT/scripts/lib/load_runtime_config.sh"
require_runtime_vars LLM_HOST LLM_PORT LLM_MODEL

ENDPOINT="http://${LLM_HOST}:${LLM_PORT}/v1/models"
echo "检查 vLLM: $ENDPOINT（期望模型: $LLM_MODEL）"
RESPONSE="$(curl --fail --silent --show-error --max-time 10 "$ENDPOINT")"
python -c 'import json,sys; payload=json.loads(sys.argv[1]); expected=sys.argv[2]; models=[item.get("id") for item in payload.get("data", [])]; assert expected in models, f"期望模型 {expected!r} 不在服务列表中: {models}"' "$RESPONSE" "$LLM_MODEL"
echo "$RESPONSE"
echo "vLLM 接口可访问。"
