#!/usr/bin/env bash
# 上传一份真实文档、轮询至终态并打印汇总，用于服务器首次全链路验证。

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$PROJECT_ROOT/scripts/lib/load_runtime_config.sh"
require_runtime_vars BACKEND_PORT API_PREFIX SMOKE_REVIEW_TIMEOUT SMOKE_REVIEW_POLL_INTERVAL

DOCUMENT_PATH="${1:-}"
if [[ -z "$DOCUMENT_PATH" || ! -f "$DOCUMENT_PATH" ]]; then
  echo "用法: bash scripts/backend/smoke_review.sh /绝对路径/招标文件.pdf" >&2
  exit 2
fi

API_BASE="http://127.0.0.1:${BACKEND_PORT}${API_PREFIX}"
echo "上传测试文档: $DOCUMENT_PATH"
CREATE_RESPONSE="$(curl --fail --silent --show-error --max-time 120 -X POST "$API_BASE/reviews" -F "documents=@${DOCUMENT_PATH}")"
REVIEW_ID="$(python -c 'import json,sys; print(json.loads(sys.argv[1])["id"])' "$CREATE_RESPONSE")"
echo "任务已创建: $REVIEW_ID"

DEADLINE=$((SECONDS + SMOKE_REVIEW_TIMEOUT))
while (( SECONDS < DEADLINE )); do
  STATUS_RESPONSE="$(curl --fail --silent --show-error --max-time 20 "$API_BASE/reviews/$REVIEW_ID/status")"
  STATUS="$(python -c 'import json,sys; print(json.loads(sys.argv[1])["status"])' "$STATUS_RESPONSE")"
  PROGRESS="$(python -c 'import json,sys; print(json.loads(sys.argv[1])["progress"])' "$STATUS_RESPONSE")"
  echo "  状态: $STATUS，进度: $PROGRESS%"
  if [[ "$STATUS" == "completed" || "$STATUS" == "failed" ]]; then
    echo "任务汇总："
    curl --fail --silent --show-error --max-time 30 "$API_BASE/reviews/$REVIEW_ID"
    echo
    if [[ "$STATUS" == "completed" ]]; then
      exit 0
    fi
    exit 1
  fi
  sleep "$SMOKE_REVIEW_POLL_INTERVAL"
done

echo "等待任务超时（${SMOKE_REVIEW_TIMEOUT}s），任务 ID: $REVIEW_ID" >&2
exit 1
