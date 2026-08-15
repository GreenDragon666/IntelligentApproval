#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export PYTHONPATH="$PROJECT_ROOT/backend${PYTHONPATH:+:$PYTHONPATH}"
CONCURRENCY="${CELERY_WORKER_CONCURRENCY:-1}"

cd "$PROJECT_ROOT"
exec celery -A app.tasks.celery_app:celery_app worker --loglevel="${LOG_LEVEL:-INFO}" --concurrency="$CONCURRENCY" --pool=prefork --hostname="approval@%h"

