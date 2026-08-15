#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export PYTHONPATH="$PROJECT_ROOT/backend${PYTHONPATH:+:$PYTHONPATH}"
SCHEDULE_PATH="${CELERY_BEAT_SCHEDULE:-$PROJECT_ROOT/runtime/celerybeat-schedule}"

mkdir -p "$(dirname "$SCHEDULE_PATH")"
cd "$PROJECT_ROOT"
exec celery -A app.tasks.celery_app:celery_app beat --loglevel="${LOG_LEVEL:-INFO}" --schedule="$SCHEDULE_PATH"

