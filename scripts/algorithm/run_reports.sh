#!/usr/bin/env bash

set -euo pipefail

python algorithm/main.py \
  --reports_path data/reports/ \
  --policy-rules data/招标文件预警规则梳理_V1.0_yy_20260610.xlsx \
  --use-llm \
  --strict-llm
