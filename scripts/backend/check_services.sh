#!/usr/bin/env bash
# 检查 API 存活与 PostgreSQL/Redis/算法配置就绪状态。

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$PROJECT_ROOT/scripts/lib/load_runtime_config.sh"
require_runtime_vars BACKEND_PORT API_PREFIX

API_BASE="http://127.0.0.1:${BACKEND_PORT}${API_PREFIX}"
echo "检查 API 存活状态: $API_BASE/health/live"
curl --fail --silent --show-error --max-time 10 "$API_BASE/health/live"
echo
echo "检查后端就绪状态: $API_BASE/health/ready"
curl --fail --silent --show-error --max-time 20 "$API_BASE/health/ready"
echo
echo "后端接口及其依赖已就绪。"
