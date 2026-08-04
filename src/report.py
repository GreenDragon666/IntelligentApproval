"""报告渲染：ApprovalReport -> JSON / Markdown。"""

from __future__ import annotations

import json

from .engine import ApprovalReport
from .schema import Status

_LABEL = {
    Status.VIOLATION: "❌ 违规",
    Status.WARNING: "⚠️ 预警",
    Status.PASS: "✅ 通过",
    Status.NA: "➖ 无法判定",
}


def to_json(report: ApprovalReport, indent: int = 2) -> str:
    return json.dumps(report.to_dict(), ensure_ascii=False, indent=indent)


def to_markdown(report: ApprovalReport) -> str:
    lines: list[str] = []
    lines.append(f"# 招标文件审批报告：{report.doc_name}")
    lines.append("")
    lines.append(f"**总体结论：{_LABEL[report.overall]}**　"
                 f"违规 {len(report.violations)} · 预警 {len(report.warnings)} · "
                 f"规则总数 {len(report.results)}")
    lines.append("")

    for r in report.results:
        lines.append(f"## {r.rule_id}　{_LABEL[r.status]}")
        lines.append(f"- **结论**：{r.summary}")
        if r.legal_basis:
            lines.append(f"- **法规依据**：{r.legal_basis}")
        if r.metrics:
            metrics = "，".join(f"{k}={v}" for k, v in r.metrics.items())
            lines.append(f"- **量化指标**：{metrics}")
        if r.evidence:
            lines.append("- **命中证据**：")
            for ev in r.evidence:
                loc = f"（{ev.location}）" if ev.location else ""
                det = f" —— {ev.detail}" if ev.detail else ""
                lines.append(f"  - {loc}「{ev.text}」{det}")
        lines.append("")
    return "\n".join(lines)
