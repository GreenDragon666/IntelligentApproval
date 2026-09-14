#!/usr/bin/env bash
# 通过与前端相同的 POST /api/reviews 接口批量上传目录中的待审文件，并等待、下载结果。

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$PROJECT_ROOT/scripts/lib/load_runtime_config.sh"
require_runtime_vars BACKEND_PORT API_PREFIX MAX_DOCUMENTS_PER_REVIEW

INPUT_DIR="${1:-}"
if [[ -z "$INPUT_DIR" || ! -d "$INPUT_DIR" ]]; then
  echo "用法: bash scripts/backend/run_batch_review.sh /待审文件目录 [结果保存目录]" >&2
  exit 2
fi

API_BASE="${BATCH_REVIEW_API_BASE:-http://127.0.0.1:${BACKEND_PORT}${API_PREFIX}}"
API_BASE="${API_BASE%/}"
TIMEOUT="${BATCH_REVIEW_TIMEOUT:-7200}"
POLL_INTERVAL="${BATCH_REVIEW_POLL_INTERVAL:-5}"
OUTPUT_ROOT="${2:-${BATCH_REVIEW_OUTPUT_ROOT:-$PROJECT_ROOT/runtime/batch-results}}"

if ! [[ "$TIMEOUT" =~ ^[1-9][0-9]*$ && "$POLL_INTERVAL" =~ ^[1-9][0-9]*$ && "$MAX_DOCUMENTS_PER_REVIEW" =~ ^[1-9][0-9]*$ ]]; then
  echo "批量数量、超时和轮询间隔配置必须是正整数" >&2
  exit 2
fi

DOCUMENTS=()
while IFS= read -r -d '' path; do
  DOCUMENTS+=("$path")
done < <(
  find "$INPUT_DIR" -maxdepth 1 -type f \
    \( -iname '*.pdf' -o -iname '*.doc' -o -iname '*.docx' -o -iname '*.docm' \
       -o -iname '*.odt' -o -iname '*.rtf' -o -iname '*.wps' -o -iname '*.txt' -o -iname '*.md' \) \
    -print0
)

DOCUMENT_COUNT="${#DOCUMENTS[@]}"
if (( DOCUMENT_COUNT == 0 )); then
  echo "目录中没有后端支持的待审文件: $INPUT_DIR" >&2
  exit 2
fi
if (( DOCUMENT_COUNT > MAX_DOCUMENTS_PER_REVIEW )); then
  echo "找到 ${DOCUMENT_COUNT} 份文件，但后端单个审查任务最多允许 ${MAX_DOCUMENTS_PER_REVIEW} 份。" >&2
  echo "请拆成多个目录，或同时调整 config/runtime.env 中的 MAX_DOCUMENTS_PER_REVIEW。" >&2
  exit 2
fi

CURL_FORM=(--fail --silent --show-error --max-time 600 -X POST "$API_BASE/reviews")
for path in "${DOCUMENTS[@]}"; do
  CURL_FORM+=(-F "documents=@${path}")
done

echo "接口地址: $API_BASE/reviews"
echo "上传目录: $INPUT_DIR"
echo "待审文件: ${DOCUMENT_COUNT} 份"
CREATE_RESPONSE="$(curl "${CURL_FORM[@]}")"
REVIEW_ID="$(python -c 'import json,sys; print(json.loads(sys.argv[1])["id"])' "$CREATE_RESPONSE")"

RUN_OUTPUT="$OUTPUT_ROOT/$REVIEW_ID"
mkdir -p "$RUN_OUTPUT/documents"
printf '%s\n' "$CREATE_RESPONSE" > "$RUN_OUTPUT/create-response.json"
echo "任务已创建: $REVIEW_ID"
echo "结果目录: $RUN_OUTPUT"

DEADLINE=$((SECONDS + TIMEOUT))
STATUS_RESPONSE=""
STATUS=""
INTERNAL_STATUS=""
PROGRESS=0
COMPLETED=0
FAILED=0
while (( SECONDS < DEADLINE )); do
  STATUS_RESPONSE="$(curl --fail --silent --show-error --max-time 30 "$API_BASE/reviews/$REVIEW_ID/status")"
  read -r STATUS INTERNAL_STATUS PROGRESS COMPLETED FAILED < <(
    python -c 'import json,sys; d=json.loads(sys.argv[1]); print(d["status"], d["internalStatus"], d["progress"], d["completedDocuments"], d["failedDocuments"])' "$STATUS_RESPONSE"
  )
  printf '[%s] 状态: %s (%s)，进度: %s%%，完成: %s，失败: %s\n' "$(date '+%F %T')" "$STATUS" "$INTERNAL_STATUS" "$PROGRESS" "$COMPLETED" "$FAILED"
  if [[ "$STATUS" == "completed" || "$STATUS" == "failed" ]]; then
    break
  fi
  sleep "$POLL_INTERVAL"
done

if [[ "$STATUS_RESPONSE" == "" || ( "$STATUS" != "completed" && "$STATUS" != "failed" ) ]]; then
  echo "等待任务超时（${TIMEOUT}s），任务仍可通过 ID 查询: $REVIEW_ID" >&2
  exit 1
fi

printf '%s\n' "$STATUS_RESPONSE" > "$RUN_OUTPUT/status.json"
curl --fail --silent --show-error --max-time 60 "$API_BASE/reviews/$REVIEW_ID" -o "$RUN_OUTPUT/summary.json"
curl --fail --silent --show-error --max-time 60 "$API_BASE/reviews/$REVIEW_ID/artifacts/brief" -o "$RUN_OUTPUT/summary_brief.md"

python -c 'import json,sys
d=json.loads(sys.argv[1])
for index,item in enumerate(d["documents"], 1):
 print(index, item["id"], item["status"], sep="\t")' "$STATUS_RESPONSE" > "$RUN_OUTPUT/documents.tsv"

while IFS=$'\t' read -r position document_id document_status; do
  detail_prefix="$RUN_OUTPUT/documents/document-$(printf '%02d' "$position")"
  curl --fail --silent --show-error --max-time 60 "$API_BASE/reviews/$REVIEW_ID/documents/$document_id" -o "${detail_prefix}.json"
  if [[ "$document_status" == "completed" ]]; then
    curl --fail --silent --show-error --max-time 60 "$API_BASE/reviews/$REVIEW_ID/documents/$document_id/artifacts/report" -o "${detail_prefix}-summary.md"
  fi
done < "$RUN_OUTPUT/documents.tsv"

echo "批量审查结束: $INTERNAL_STATUS"
echo "简要报告: $RUN_OUTPUT/summary_brief.md"
echo "汇总数据: $RUN_OUTPUT/summary.json"
echo "文件详情: $RUN_OUTPUT/documents/"

if [[ "$INTERNAL_STATUS" == "completed" ]]; then
  exit 0
fi
exit 1
