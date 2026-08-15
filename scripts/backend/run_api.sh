#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export PYTHONPATH="$PROJECT_ROOT/backend${PYTHONPATH:+:$PYTHONPATH}"
HOST="${BACKEND_HOST:-0.0.0.0}"
PORT="${BACKEND_PORT:-8000}"
WORKERS="${BACKEND_API_WORKERS:-2}"

cd "$PROJECT_ROOT"
exec uvicorn app.main:app --host "$HOST" --port "$PORT" --workers "$WORKERS" --proxy-headers

