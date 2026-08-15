#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$PROJECT_ROOT/scripts/lib/load_runtime_config.sh"
require_runtime_vars POSTGRES_PORT POSTGRES_DB POSTGRES_USER POSTGRES_PASSWORD REDIS_PORT
cd "$PROJECT_ROOT"
exec docker compose -f backend/docker-compose.infrastructure.yml up -d
