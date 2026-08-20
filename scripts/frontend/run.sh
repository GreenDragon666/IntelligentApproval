#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$PROJECT_ROOT/scripts/lib/load_runtime_config.sh"
require_runtime_vars VITE_REVIEW_API_URL
cd "$PROJECT_ROOT/frontend"
# 项目位于 CIFS 网络盘，不支持 symlink；--no-bin-links 跳过 node_modules/.bin 软链接，直接用 node 启动 vite 入口（绕开 npm run 对 .bin 的依赖）。
npm install --no-bin-links
exec node node_modules/vite/bin/vite.js --host 0.0.0.0
# 否则使用
# npm install
# exec npm run dev -- --host 0.0.0.0