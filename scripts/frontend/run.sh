#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$PROJECT_ROOT/scripts/lib/load_runtime_config.sh"
require_runtime_vars VITE_REVIEW_API_URL
cd "$PROJECT_ROOT/frontend"
npm install
exec npm run dev -- --host 0.0.0.0
