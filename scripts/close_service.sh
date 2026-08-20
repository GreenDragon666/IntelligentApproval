#!/usr/bin/env bash
# 一键停止 open_service.sh 启动的全部服务，对称收尾并逐个报告。
# 不用 set -e：即使某个服务已不在，也要继续把其余服务停干净。

set -uo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$PROJECT_ROOT/scripts/lib/load_runtime_config.sh"

INFRA_ENV="${INFRA_CONDA_ENV:-approval-infra}"
PG_DATA="${PG_DATA_DIR:-/home/zyl/.local/share/intelligent-approval/postgresql}"

# 按命令签名停止后台服务：先 TERM，等不退再 KILL。参数: 名称 签名
stop_bg() {
  local name="$1" sig="$2"
  if ! pgrep -f "$sig" >/dev/null 2>&1; then
    echo "[$name] 未在运行"
    return 0
  fi
  pkill -TERM -f "$sig" 2>/dev/null || true
  local i
  for ((i = 1; i <= 10; i++)); do
    pgrep -f "$sig" >/dev/null 2>&1 || break
    sleep 1
  done
  if pgrep -f "$sig" >/dev/null 2>&1; then
    pkill -KILL -f "$sig" 2>/dev/null || true
    echo "[$name] 已强制停止"
  else
    echo "[$name] 已停止"
  fi
}

echo "== 后端 (api / beat / worker) =="
stop_bg api "uvicorn app.main:app"
stop_bg beat "app.tasks.celery_app:celery_app beat"
stop_bg worker "app.tasks.celery_app:celery_app worker"

echo "== vLLM =="
stop_bg vllm "vllm serve"

echo "== 基础设施 (Redis / PostgreSQL) =="
conda run -n "$INFRA_ENV" redis-cli -h 127.0.0.1 -p 6379 shutdown 2>/dev/null \
  && echo "[Redis] 已停止" || echo "[Redis] 未在运行"
if conda run -n "$INFRA_ENV" pg_ctl -D "$PG_DATA" stop 2>/dev/null; then
  echo "[PostgreSQL] 已停止"
else
  echo "[PostgreSQL] 未在运行"
fi

echo
echo "全部服务已停止。"
