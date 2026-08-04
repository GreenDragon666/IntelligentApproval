"""核心数据结构：规则输入上下文 与 checker 输出结果。

步骤三边界：
- 输入由上游（或人工）按契约准备好，本模块只消费结构化数据。
- checker 是纯函数 `check(ctx: TenderContext) -> Result`，签名固定，便于代码生成与注册。
- 只依赖标准库。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any


class Status(str, Enum):
    VIOLATION = "violation"  # 违规
    WARNING = "warning"      # 预警
    PASS = "pass"            # 通过
    NA = "not_applicable"    # 该规则所需输入缺失，无法判定


@dataclass
class Evidence:
    """命中证据：用于报告回引原文。"""
    text: str
    location: str = ""
    detail: str = ""


@dataclass
class RuleResult:
    rule_id: str
    status: Status
    summary: str
    legal_basis: str = ""
    evidence: list[Evidence] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d


@dataclass
class TenderContext:
    """一次审批的输入上下文（步骤三的唯一输入形态）。

    由上游关键词匹配 / 人工按规则准备，本仓库不负责从 PDF 抽取。
    字段按需填充；某规则所需字段缺失时，对应 checker 返回 Status.NA。
    """
    doc_name: str = ""

    # 全文与分节（文本类规则）
    full_text: str = ""
    sections: dict[str, str] = field(default_factory=dict)  # 如 {"项目概况": "..."}

    # 结构化字段（阈值/比例类规则）
    fields: dict[str, Any] = field(default_factory=dict)
    # 约定 key 示例：
    #   project_type, contract_amount, warranty_months, response_hours,
    #   registered_capital_req, project_actual_capital_need,
    #   building_height, required_qualification_level

    # 关联表（如 rule_1 三表；当前可略过）
    tables: dict[str, list[dict]] = field(default_factory=dict)

    # 参照库（如立项批复文本、政策库、embedding 注入）
    references: dict[str, Any] = field(default_factory=dict)

    def section(self, name: str) -> str:
        return self.sections.get(name, "")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TenderContext":
        return cls(
            doc_name=data.get("doc_name", ""),
            full_text=data.get("full_text", ""),
            sections=dict(data.get("sections") or {}),
            fields=dict(data.get("fields") or {}),
            tables=dict(data.get("tables") or {}),
            references=dict(data.get("references") or {}),
        )

    @classmethod
    def from_json_file(cls, path: str | Path) -> "TenderContext":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"输入 JSON 须为对象: {path}")
        return cls.from_dict(raw)

    def to_dict(self) -> dict[str, Any]:
        return {
            "doc_name": self.doc_name,
            "full_text": self.full_text,
            "sections": self.sections,
            "fields": self.fields,
            "tables": self.tables,
            "references": self.references,
        }
