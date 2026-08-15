#!/usr/bin/env bash
# 首次部署时创建本机运行配置；不会覆盖已有配置。

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE_FILE="$PROJECT_ROOT/config/runtime.env.example"
TARGET_FILE="$PROJECT_ROOT/config/runtime.env"

if [[ -e "$TARGET_FILE" ]]; then
  echo "运行配置已存在，未覆盖: $TARGET_FILE"
  exit 0
fi

cp "$SOURCE_FILE" "$TARGET_FILE"
chmod 600 "$TARGET_FILE"
echo "已创建运行配置: $TARGET_FILE"
echo "请编辑该文件中的数据库密码、规则路径、模型路径、GPU 和服务地址。"
