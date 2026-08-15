#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$PROJECT_ROOT/scripts/lib/load_runtime_config.sh"
require_algorithm_runtime_vars
require_runtime_vars ALGORITHM_REPORTS_PATH ALGORITHM_CONTINUE_ON_ERROR

ARGS=(
  --reports_path "$ALGORITHM_REPORTS_PATH"
  --policy-rules "$POLICY_RULES_PATH"
  --max-section-pages "$ALGORITHM_MAX_SECTION_PAGES"
  --candidate-count "$ALGORITHM_CANDIDATE_COUNT"
  --evidence-count "$ALGORITHM_EVIDENCE_COUNT"
  --minimum-score "$ALGORITHM_MINIMUM_SCORE"
  --match-workers "$MATCHING_WORKERS"
  --check-workers "$SEMANTIC_WORKERS"
)
runtime_bool_is_true "$ALGORITHM_USE_EMBEDDING" || ARGS+=(--no-embedding)
runtime_bool_is_true "$ALGORITHM_USE_LLM_MATCHING" && ARGS+=(--use-llm)
runtime_bool_is_true "$ALGORITHM_STRICT_LLM" && ARGS+=(--strict-llm)
runtime_bool_is_true "$ALGORITHM_ENABLE_LLM_CHECK" || ARGS+=(--no-llm-check)
runtime_bool_is_true "$ALGORITHM_LLM_REVIEW" && ARGS+=(--review)
runtime_bool_is_true "$ALGORITHM_CONTINUE_ON_ERROR" && ARGS+=(--continue-on-error)

cd "$PROJECT_ROOT"
python algorithm/main.py "${ARGS[@]}"
