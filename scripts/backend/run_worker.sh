#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$PROJECT_ROOT/scripts/lib/load_runtime_config.sh"
require_backend_runtime_vars
require_algorithm_runtime_vars
export PYTHONPATH="$PROJECT_ROOT/backend${PYTHONPATH:+:$PYTHONPATH}"

cd "$PROJECT_ROOT"
exec celery -A app.tasks.celery_app:celery_app worker --loglevel="$LOG_LEVEL" --concurrency="$CELERY_WORKER_CONCURRENCY" --pool=prefork --hostname="approval@%h"
