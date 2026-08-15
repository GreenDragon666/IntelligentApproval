#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$PROJECT_ROOT/scripts/lib/load_runtime_config.sh"
require_runtime_vars DATABASE_URL
export PYTHONPATH="$PROJECT_ROOT/backend${PYTHONPATH:+:$PYTHONPATH}"

cd "$PROJECT_ROOT"
alembic -c backend/alembic.ini upgrade head
