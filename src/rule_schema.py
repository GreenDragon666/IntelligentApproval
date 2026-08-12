"""正式输入契约、规则判定输出契约与案件报告数据结构。"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class Status(str, Enum):
    VIOLATION = "violation"
    WARNING = "warning"
    PASS = "pass"
    INSUFFICIENT_INPUT = "insufficient_input"
    ERROR = "error"


@dataclass(frozen=True)
class PageRange:
    """闭区间页码；单页时 start == end。"""

    start: int
    end: int

    def __post_init__(self) -> None:
        if self.start < 1 or self.end < self.start:
            raise ValueError(f"非法页码范围: {self.start}-{self.end}")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PageRange":
        return cls(start=int(data["start"]), end=int(data["end"]))


@dataclass(frozen=True)
class EvidenceLocation:
    file: str
    section: str
    pdf_pages: PageRange
    document_pages: PageRange | None = None
    page_basis: str = "original_pdf"

    def __post_init__(self) -> None:
        if not self.file.strip():
            raise ValueError("证据文件名不能为空")
        if not self.section.strip():
            raise ValueError("证据章节不能为空")
        if self.page_basis not in {"original_pdf", "converted_pdf", "logical_page"}:
            raise ValueError(f"不支持的 page_basis: {self.page_basis}")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EvidenceLocation":
        document_pages = data.get("document_pages")
        return cls(
            file=str(data["file"]).strip(),
            section=str(data["section"]).strip(),
            pdf_pages=PageRange.from_dict(data["pdf_pages"]),
            document_pages=(
                PageRange.from_dict(document_pages) if document_pages is not None else None
            ),
            page_basis=str(data.get("page_basis", "original_pdf")).strip(),
        )


@dataclass(frozen=True)
class MatchedEvidence:
    location: EvidenceLocation
    text: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MatchedEvidence":
        return cls(
            location=EvidenceLocation.from_dict(data["location"]),
            text=str(data.get("text", "")).strip(),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MatchedRule:
    rule_id: int
    rule_raw: str
    rule_text: str
    evidence: list[MatchedEvidence] = field(default_factory=list)
    check_method: str = "大模型分析"
    structured_fields: str = ""

    def __post_init__(self) -> None:
        if isinstance(self.rule_id, bool) or not isinstance(self.rule_id, int):
            raise TypeError("rule_id 必须是 int")
        if self.rule_id < 1:
            raise ValueError("rule_id 必须是正整数")
        if not self.rule_raw.strip():
            raise ValueError(f"规则 {self.rule_id} 缺少 rule_raw")
        if not self.rule_text.strip():
            raise ValueError(f"规则 {self.rule_id} 缺少 rule_text")
        if not self.check_method.strip():
            raise ValueError(f"规则 {self.rule_id} 缺少 check_method")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MatchedRule":
        rule_id = data.get("rule_id")
        if isinstance(rule_id, bool) or not isinstance(rule_id, int):
            raise TypeError(f"rule_id 必须是 int，实际为 {type(rule_id).__name__}")
        return cls(
            rule_id=rule_id,
            rule_raw=str(data.get("rule_raw", "")).strip(),
            rule_text=str(data.get("rule_text", "")).strip(),
            check_method=str(data.get("check_method", "大模型分析")).strip() or "大模型分析",
            structured_fields=str(data.get("structured_fields", "")).strip(),
            evidence=[MatchedEvidence.from_dict(item) for item in data.get("evidence", [])],
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SourceDocument:
    file: str

    def __post_init__(self) -> None:
        if not self.file.strip():
            raise ValueError("source.file 不能为空")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SourceDocument":
        extra = set(data) - {"file"}
        if extra:
            raise ValueError(f"source 只允许 file 字段，发现: {', '.join(sorted(extra))}")
        return cls(file=str(data["file"]).strip())


@dataclass(frozen=True)
class MatchedCase:
    case_id: str
    source: SourceDocument
    rules: list[MatchedRule]

    def __post_init__(self) -> None:
        if not self.case_id.strip():
            raise ValueError("case_id 不能为空")
        if not self.rules:
            raise ValueError("rules 不能为空")
        ids = [rule.rule_id for rule in self.rules]
        if len(ids) != len(set(ids)):
            raise ValueError("rule_id 不得重复")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MatchedCase":
        return cls(
            case_id=str(data.get("case_id", "")).strip(),
            source=SourceDocument.from_dict(data["source"]),
            rules=[MatchedRule.from_dict(item) for item in data.get("rules", [])],
        )

    @classmethod
    def from_json_file(cls, path: str | Path) -> "MatchedCase":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("案件 JSON 须为对象")
        return cls.from_dict(data)

    def get_rule(self, rule_id: int) -> MatchedRule:
        for rule in self.rules:
            if rule.rule_id == rule_id:
                return rule
        raise KeyError(f"案件中不存在规则 {rule_id}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Finding:
    """规则判定命中的一条结论及其对输入 evidence 的回引。"""

    evidence_index: int
    quote: str
    reason: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Finding":
        return cls(
            evidence_index=int(data["evidence_index"]),
            quote=str(data.get("quote", "")),
            reason=str(data.get("reason", "")),
        )


@dataclass(frozen=True)
class RuleResult:
    rule_id: int
    status: Status
    summary: str
    analysis: str = ""
    legal_basis: str = ""
    findings: list[Finding] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    confidence: float | None = None
    missing_inputs: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RuleResult":
        return cls(
            rule_id=int(data["rule_id"]),
            status=Status(data["status"]),
            summary=str(data.get("summary", "")),
            analysis=str(data.get("analysis", "")),
            legal_basis=str(data.get("legal_basis", "")),
            findings=[Finding.from_dict(item) for item in data.get("findings", [])],
            metrics=dict(data.get("metrics") or {}),
            confidence=(float(data["confidence"]) if data.get("confidence") is not None else None),
            missing_inputs=[str(item) for item in data.get("missing_inputs", [])],
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data


@dataclass(frozen=True)
class ReviewResult:
    approved: bool
    feedback: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RuleRun:
    rule_id: int
    rule_raw: str
    check_method: str = ""
    executor: str = ""
    cache_key: str = ""
    cached: bool = False
    attempts: int = 0
    result: RuleResult | None = None
    review: ReviewResult | None = None
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "rule_raw": self.rule_raw,
            "check_method": self.check_method,
            "executor": self.executor,
            "cache_key": self.cache_key,
            "cached": self.cached,
            "attempts": self.attempts,
            "result": self.result.to_dict() if self.result else None,
            "review": self.review.to_dict() if self.review else None,
            "error": self.error,
        }


@dataclass
class ApprovalReport:
    case_id: str
    source_file: str
    rules: list[RuleRun] = field(default_factory=list)

    @property
    def overall(self) -> str:
        statuses = [run.result.status for run in self.rules if run.result]
        if Status.VIOLATION in statuses:
            return Status.VIOLATION.value
        if any(run.error for run in self.rules):
            return "partial"
        if any(status in {Status.ERROR, Status.INSUFFICIENT_INPUT} for status in statuses):
            return "partial"
        if Status.WARNING in statuses:
            return Status.WARNING.value
        return Status.PASS.value if statuses else "partial"

    def to_dict(self) -> dict[str, Any]:
        counts = {status.value: 0 for status in Status}
        for run in self.rules:
            if run.result:
                counts[run.result.status.value] += 1
        return {
            "case_id": self.case_id,
            "source_file": self.source_file,
            "overall": self.overall,
            "summary": {
                **counts,
                "pipeline_error": sum(bool(run.error) for run in self.rules),
            },
            "rules": [run.to_dict() for run in self.rules],
        }
