"""按规则内容哈希保存并复用全局 checker。"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import settings
from .schema import MatchedRule


def rule_digest(rule_text: str) -> str:
    normalized = "\n".join(line.rstrip() for line in rule_text.replace("\r\n", "\n").split("\n"))
    return hashlib.sha256(normalized.strip().encode("utf-8")).hexdigest()


def checker_key(rule: MatchedRule) -> str:
    return f"rule_{rule.rule_id}_{rule_digest(rule.rule_text)[:12]}"


class CheckerStore:
    def __init__(self, root: str | Path | None = None):
        self.root = Path(root or settings.generated_dir)

    def code_path(self, rule: MatchedRule) -> Path:
        return self.root / f"{checker_key(rule)}.py"

    def metadata_path(self, rule: MatchedRule) -> Path:
        return self.root / f"{checker_key(rule)}.json"

    def exists(self, rule: MatchedRule) -> bool:
        return self.code_path(rule).is_file()

    def load(self, rule: MatchedRule) -> str:
        return self.code_path(rule).read_text(encoding="utf-8")

    def save(self, rule: MatchedRule, code: str, *, attempts: int) -> tuple[Path, Path]:
        self.root.mkdir(parents=True, exist_ok=True)
        code_path = self.code_path(rule)
        metadata_path = self.metadata_path(rule)
        code_path.write_text(code.rstrip() + "\n", encoding="utf-8")
        metadata: dict[str, Any] = {
            "checker_key": checker_key(rule),
            "rule_id": rule.rule_id,
            "rule_digest": rule_digest(rule.rule_text),
            "model": settings.llm_model,
            "generation_attempts": attempts,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        metadata_path.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return code_path, metadata_path
