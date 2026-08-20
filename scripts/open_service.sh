#!/usr/bin/env bash
# 一键在后台静默启动全部服务，按依赖顺序逐个等待就绪后统一报告可用。
# 只复用 scripts/ 下已有入口，不重复实现任何启动细节；后台化与就绪检测都在本脚本。
# 关闭见 scripts/close_service.sh。

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$PROJECT_ROOT/scripts/lib/load_runtime_config.sh"
require_runtime_vars LLM_HOST LLM_PORT BACKEND_PORT API_PREFIX

INFRA_ENV="${INFRA_CONDA_ENV:-approval-infra}"
APP_ENV="${APP_CONDA_ENV:-approval}"
PG_DATA="${PG_DATA_DIR:-/home/zyl/.local/share/intelligent-approval/postgresql}"
PG_LOG="${PG_LOG_FILE:-/home/zyl/.local/share/intelligent-approval/postgresql.log}"
REDIS_DIR="$PROJECT_ROOT/runtime/infrastructure/redis"
LOG_DIR="$PROJECT_ROOT/runtime/services"
VLLM_READY_TRIES="${VLLM_READY_TRIES:-180}"   # 每次间隔 2s，默认最多等待 6 分钟
mkdir -p "$REDIS_DIR" "$LOG_DIR"

# 后台常驻启动，日志落盘；命令签名已存在则跳过。参数: 名称 签名 命令...
start_bg() {
  local name="$1" sig="$2"; shift 2
  if pgrep -f "$sig" >/dev/null 2>&1; then
    echo "[$name] 已在运行，跳过"
    return 0
  fi
  nohup "$@" >"$LOG_DIR/$name.log" 2>&1 &
  echo "[$name] 已后台启动，日志 $LOG_DIR/$name.log"
}

# 轮询直到就绪命令成功，超时即失败中止。参数: 名称 次数 命令...
wait_ready() {
  local name="$1" tries="$2"; shift 2
  local i
  for ((i = 1; i <= tries; i++)); do
    if "$@" >/dev/null 2>&1; then
      echo "[$name] 就绪 ✓"
      return 0
    fi
    sleep 2
  done
  echo "[$name] 等待就绪超时，请检查日志。" >&2
  return 1
}

echo "== 基础设施 (PostgreSQL / Redis) =="
conda run -n "$INFRA_ENV" pg_ctl -D "$PG_DATA" -l "$PG_LOG" \
  -o "-h 127.0.0.1 -p 5432 -k /tmp" start || true
wait_ready PostgreSQL 15 conda run -n "$INFRA_ENV" pg_isready -h 127.0.0.1 -p 5432

conda run -n "$INFRA_ENV" redis-server \
  --bind 127.0.0.1 --port 6379 \
  --dir "$REDIS_DIR" --appendonly yes --daemonize yes \
  --pidfile "$REDIS_DIR/redis.pid" --logfile "$REDIS_DIR/redis.log" || true
wait_ready Redis 15 conda run -n "$INFRA_ENV" redis-cli -h 127.0.0.1 -p 6379 ping

echo "== vLLM (Qwen3-8B) =="
start_bg vllm "vllm serve" \
  conda run --no-capture-output -n "$APP_ENV" bash "$PROJECT_ROOT/scripts/algorithm/serve_vllm_qwen3_8b.sh"
wait_ready vLLM "$VLLM_READY_TRIES" bash "$PROJECT_ROOT/scripts/algorithm/check_vllm.sh"

echo "== 数据库迁移 =="
conda run --no-capture-output -n "$APP_ENV" bash "$PROJECT_ROOT/scripts/backend/migrate.sh"

echo "== 后端 (worker / beat / api) =="
start_bg worker "app.tasks.celery_app:celery_app worker" \
  conda run --no-capture-output -n "$APP_ENV" bash "$PROJECT_ROOT/scripts/backend/run_worker.sh"
start_bg beat "app.tasks.celery_app:celery_app beat" \
  conda run --no-capture-output -n "$APP_ENV" bash "$PROJECT_ROOT/scripts/backend/run_beat.sh"
start_bg api "uvicorn app.main:app" \
  conda run --no-capture-output -n "$APP_ENV" bash "$PROJECT_ROOT/scripts/backend/run_api.sh"
wait_ready 后端 60 bash "$PROJECT_ROOT/scripts/backend/check_services.sh"

echo
echo "全部服务已就绪:"
echo "  PostgreSQL  127.0.0.1:5432"
echo "  Redis       127.0.0.1:6379"
echo "  vLLM        http://${LLM_HOST}:${LLM_PORT}/v1"
echo "  API         http://127.0.0.1:${BACKEND_PORT}${API_PREFIX}"
echo "日志目录: $LOG_DIR   停止服务: bash scripts/close_service.sh"
