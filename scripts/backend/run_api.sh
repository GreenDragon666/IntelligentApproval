#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$PROJECT_ROOT/scripts/lib/load_runtime_config.sh"
require_backend_runtime_vars
export PYTHONPATH="$PROJECT_ROOT/backend${PYTHONPATH:+:$PYTHONPATH}"

cd "$PROJECT_ROOT"
exec uvicorn app.main:app --host "$BACKEND_HOST" --port "$BACKEND_PORT" --workers "$BACKEND_API_WORKERS" --proxy-headers
