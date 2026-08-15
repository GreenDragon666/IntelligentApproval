#!/usr/bin/env bash
# Development/single-server entry point. Production should supervise the same
# three commands independently with systemd, Supervisor or Kubernetes.

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PIDS=()

cleanup() {
  for pid in "${PIDS[@]}"; do
    kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

"$PROJECT_ROOT/scripts/backend/migrate.sh"
"$PROJECT_ROOT/scripts/backend/run_api.sh" & PIDS+=("$!")
"$PROJECT_ROOT/scripts/backend/run_worker.sh" & PIDS+=("$!")
"$PROJECT_ROOT/scripts/backend/run_beat.sh" & PIDS+=("$!")

wait -n "${PIDS[@]}"

