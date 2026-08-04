"""运行时校验引擎：加载 checker 注册表，逐规则执行，汇总结果。"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import registry
from .schema import TenderContext, RuleResult, Status


@dataclass
class ApprovalReport:
    doc_name: str
    results: list[RuleResult] = field(default_factory=list)

    @property
    def violations(self) -> list[RuleResult]:
        return [r for r in self.results if r.status == Status.VIOLATION]

    @property
    def warnings(self) -> list[RuleResult]:
        return [r for r in self.results if r.status == Status.WARNING]

    @property
    def overall(self) -> Status:
        if self.violations:
            return Status.VIOLATION
        if self.warnings:
            return Status.WARNING
        return Status.PASS

    def to_dict(self) -> dict:
        return {
            "doc_name": self.doc_name,
            "overall": self.overall.value,
            "summary": {
                "violation": len(self.violations),
                "warning": len(self.warnings),
                "pass": sum(1 for r in self.results if r.status == Status.PASS),
                "not_applicable": sum(1 for r in self.results if r.status == Status.NA),
            },
            "results": [r.to_dict() for r in self.results],
        }


def run(ctx: TenderContext, doc_name: str = "", rule_ids: list[str] | None = None) -> ApprovalReport:
    """对单份文件跑全部（或指定）规则。checker 抛异常时记为 NA，不中断整体审批。"""
    registry.load_builtin()
    checkers = registry.all_checkers()
    ids = rule_ids or sorted(checkers)

    results: list[RuleResult] = []
    for rid in ids:
        fn = checkers.get(rid)
        if fn is None:
            results.append(RuleResult(rid, Status.NA, f"未找到 checker: {rid}"))
            continue
        try:
            results.append(fn(ctx))
        except Exception as e:  # 单条规则失败不影响其余
            results.append(RuleResult(rid, Status.NA, f"checker 执行异常: {e!r}"))
    return ApprovalReport(doc_name=doc_name, results=results)
