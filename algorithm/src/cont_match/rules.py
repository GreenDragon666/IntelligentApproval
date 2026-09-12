"""从正式 JSON 加载政策规则。

规则由本项目之外的程序统一转换为固定 JSON 契约后交给本项目读取。顶层可为规则数组，
或包含 ``rules`` 数组的对象。每条规则的 ``rule_text`` 可以是拆分好的子字段对象
（description/legal_basis/formula/dev_note），载入时会重组为下游 ``rule_parts`` 认识的
``【描述】/【法规依据】/【公式】/【开发说明】`` 块字符串；若已是字符串则原样使用。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ..page_schema import PolicyRule

# rule_text 子字段 → 下游 rule_parts 使用的中文块标题（顺序即重组顺序）。
_TEXT_BLOCKS = (
    ("description", "描述"),
    ("legal_basis", "法规依据"),
    ("formula", "公式"),
    ("dev_note", "开发说明"),
)


def _rule_id(value: Any, fallback: int) -> int:
    """解析整数序号，空值时使用行号。"""
    if value is None or str(value).strip() == "":
        return fallback
    match = re.search(r"\d+", str(value))
    if not match:
        raise ValueError(f"无法解析规则序号: {value!r}")
    return int(match.group())


def _rule_text(value: Any) -> str:
    """将 rule_text 归一化为块字符串：dict 按固定顺序重组，str 原样返回。"""
    if isinstance(value, dict):
        parts = []
        for key, title in _TEXT_BLOCKS:
            body = str(value.get(key) or "").strip()
            if body:
                parts.append(f"【{title}】{body}")
        return "\n".join(parts)
    return str(value or "").strip()


def _match_hints(value: Any) -> list[str]:
    """match_hints 支持字符串或字符串数组，去重保序。"""
    if not value:
        return []
    raw = value if isinstance(value, list) else [value]
    hints: list[str] = []
    for item in raw:
        text = str(item).strip()
        if text and text not in hints:
            hints.append(text)
    return hints


def _rows_to_rules(rows: list[dict[str, Any]]) -> list[PolicyRule]:
    """将 JSON 行转成规则，重组 rule_text 并校验重复序号。"""
    rules: list[PolicyRule] = []
    for row_number, row in enumerate(rows, start=1):
        rule_raw = str(row.get("rule_raw") or "").strip()
        rule_text = _rule_text(row.get("rule_text"))
        if not rule_raw and not rule_text:
            continue
        if not rule_raw or not rule_text:
            raise ValueError(f"第 {row_number} 条规则缺少 rule_raw 或 rule_text")
        rules.append(
            PolicyRule(
                rule_id=_rule_id(row.get("rule_id"), row_number),
                rule_raw=rule_raw,
                rule_text=rule_text,
                check_method=str(row.get("check_method") or "").strip() or "大模型分析",
                structured_fields=str(row.get("structured_fields") or "").strip(),
                match_hints=_match_hints(row.get("match_hints")),
            )
        )
    if not rules:
        raise ValueError("规则文件中没有可用规则")
    ids = [rule.rule_id for rule in rules]
    if len(ids) != len(set(ids)):
        raise ValueError("规则序号重复")
    return rules


def _load_json(path: Path) -> list[dict[str, Any]]:
    """读取规则数组或包含 ``rules`` 数组的对象。"""
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        rows = data.get("rules")
    else:
        rows = data
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ValueError("JSON 必须是规则数组，或包含 rules 数组的对象")
    return rows


def load_policy_rules(path: str | Path) -> list[PolicyRule]:
    """政策规则加载入口；只接受正式 JSON。"""
    rule_path = Path(path)
    if not rule_path.is_file():
        raise FileNotFoundError(rule_path)
    if rule_path.suffix.lower() != ".json":
        raise ValueError(f"不支持的规则文件格式: {rule_path.suffix}；政策规则须为 JSON")
    return _rows_to_rules(_load_json(rule_path))
