#!/usr/bin/env bash
# 后台批量提交小批量文档到后端 API，逐个轮询至终态并把汇总落地到本地，供不启用前端时测试。
# 每份文档单独建一个 review，便于逐份对比结果。走 API，不触碰 algorithm/main.py。

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$PROJECT_ROOT/scripts/lib/load_runtime_config.sh"
require_runtime_vars BACKEND_PORT API_PREFIX SMOKE_REVIEW_TIMEOUT SMOKE_REVIEW_POLL_INTERVAL

# 参数：一个或多个文件路径，或一个目录（递归取其中支持的文档）。缺省用 data/reports。
INPUTS=("$@")
if [[ ${#INPUTS[@]} -eq 0 ]]; then
  INPUTS=("$PROJECT_ROOT/data/reports")
fi

FILES=()
for path in "${INPUTS[@]}"; do
  if [[ -d "$path" ]]; then
    while IFS= read -r found; do FILES+=("$found"); done \
      < <(find "$path" -type f \( -iname '*.pdf' -o -iname '*.doc' -o -iname '*.docx' \) | sort)
  elif [[ -f "$path" ]]; then
    FILES+=("$path")
  else
    echo "跳过不存在的路径: $path" >&2
  fi
done

if [[ ${#FILES[@]} -eq 0 ]]; then
  echo "用法: bash scripts/backend/batch_review.sh <文件或目录> [更多...]" >&2
  echo "  不带参数时默认扫描 data/reports 下的 pdf/doc/docx" >&2
  exit 2
fi

API_BASE="http://127.0.0.1:${BACKEND_PORT}${API_PREFIX}"
OUTPUT_DIR="$PROJECT_ROOT/runtime/batch_review"
mkdir -p "$OUTPUT_DIR"

echo "API: $API_BASE"
echo "待处理: ${#FILES[@]} 份；汇总输出目录: $OUTPUT_DIR"

# 逐份提交，记录 review_id → 文件名。
declare -A REVIEW_FILE
for file in "${FILES[@]}"; do
  echo "上传: $file"
  CREATE_RESPONSE="$(curl --fail --silent --show-error --max-time 120 -X POST "$API_BASE/reviews" -F "documents=@${file}")"
  REVIEW_ID="$(python -c 'import json,sys; print(json.loads(sys.argv[1])["id"])' "$CREATE_RESPONSE")"
  REVIEW_FILE["$REVIEW_ID"]="$(basename "$file")"
  echo "  → review_id: $REVIEW_ID"
done

echo ""
echo "轮询至终态（单份超时 ${SMOKE_REVIEW_TIMEOUT}s）..."
FAILED=0
for review_id in "${!REVIEW_FILE[@]}"; do
  name="${REVIEW_FILE[$review_id]}"
  DEADLINE=$((SECONDS + SMOKE_REVIEW_TIMEOUT))
  while (( SECONDS < DEADLINE )); do
    STATUS_RESPONSE="$(curl --fail --silent --show-error --max-time 20 "$API_BASE/reviews/$review_id/status")"
    STATUS="$(python -c 'import json,sys; print(json.loads(sys.argv[1])["status"])' "$STATUS_RESPONSE")"
    PROGRESS="$(python -c 'import json,sys; print(json.loads(sys.argv[1])["progress"])' "$STATUS_RESPONSE")"
    echo "[$(date '+%H:%M:%S')] $name ($review_id): $STATUS $PROGRESS%"
    if [[ "$STATUS" == "completed" || "$STATUS" == "failed" ]]; then
      curl --fail --silent --show-error --max-time 30 "$API_BASE/reviews/$review_id" \
        > "$OUTPUT_DIR/${review_id}.json"
      echo "  汇总已保存: runtime/batch_review/${review_id}.json"
      [[ "$STATUS" == "failed" ]] && FAILED=$((FAILED + 1))
      break
    fi
    sleep "$SMOKE_REVIEW_POLL_INTERVAL"
  done
done

echo ""
echo "完成：${#REVIEW_FILE[@]} 份，其中失败 ${FAILED} 份。汇总在 $OUTPUT_DIR"
[[ $FAILED -eq 0 ]]
