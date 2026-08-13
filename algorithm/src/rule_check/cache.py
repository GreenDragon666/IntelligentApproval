"""案件判定结果缓存：支持中断续跑、强制重检和恢复上一版本。"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..rule_schema import MatchedRule, RuleResult

ENGINE_VERSION = "rule-check-v2"


def decision_digest(rule: MatchedRule) -> str:
    payload = {
        "engine_version": ENGINE_VERSION,
        "rule_id": rule.rule_id,
        "rule_raw": rule.rule_raw,
        "rule_text": rule.rule_text,
        "check_method": rule.check_method,
        "structured_fields": rule.structured_fields,
        "evidence": [item.to_dict() for item in rule.evidence],
    }
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def decision_key(rule: MatchedRule) -> str:
    return f"rule_{rule.rule_id}_{decision_digest(rule)[:16]}"


class DecisionCache:
    def __init__(self, root: str | Path):
        self.root = Path(root)

    def path(self, rule: MatchedRule) -> Path:
        return self.root / f"{decision_key(rule)}.json"

    def load(self, rule: MatchedRule) -> tuple[RuleResult, dict[str, Any]] | None:
        path = self.path(rule)
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return None
        if data.get("engine_version") != ENGINE_VERSION or data.get("digest") != decision_digest(rule):
            return None
        return RuleResult.from_dict(data["result"]), data

    def save(self, rule: MatchedRule, result: RuleResult, *, executor: str, attempts: int, error: str = "", structured_result: RuleResult | None = None, analysis_error: str = "", analysis_raw: str = "") -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.path(rule)
        if path.is_file():
            history = self.root / "history"
            history.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            shutil.copy2(path, history / f"{path.stem}_{stamp}.json")
        data = {
            "engine_version": ENGINE_VERSION,
            "digest": decision_digest(rule),
            "cache_key": decision_key(rule),
            "rule_id": rule.rule_id,
            "check_method": rule.check_method,
            "executor": executor,
            "attempts": attempts,
            "error": error,
            "analysis_error": analysis_error,
            "analysis_raw": analysis_raw,
            "structured_result": structured_result.to_dict() if structured_result else None,
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "result": result.to_dict(),
        }
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.root, prefix=path.stem + ".", suffix=".tmp", delete=False) as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            temporary = Path(handle.name)
        temporary.replace(path)
        return path

    def rollback(self, rule: MatchedRule) -> bool:
        history = self.root / "history"
        candidates = sorted(history.glob(f"{decision_key(rule)}_*.json"), reverse=True) if history.is_dir() else []
        if not candidates:
            return False
        self.root.mkdir(parents=True, exist_ok=True)
        shutil.copy2(candidates[0], self.path(rule))
        return True
