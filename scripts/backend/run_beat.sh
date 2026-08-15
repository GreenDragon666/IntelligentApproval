#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$PROJECT_ROOT/scripts/lib/load_runtime_config.sh"
require_backend_runtime_vars
export PYTHONPATH="$PROJECT_ROOT/backend${PYTHONPATH:+:$PYTHONPATH}"

mkdir -p "$(dirname "$CELERY_BEAT_SCHEDULE")"
cd "$PROJECT_ROOT"
exec celery -A app.tasks.celery_app:celery_app beat --loglevel="$LOG_LEVEL" --schedule="$CELERY_BEAT_SCHEDULE"
