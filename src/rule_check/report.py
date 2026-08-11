"""案件审批报告的 JSON 与 Markdown 渲染。"""

from __future__ import annotations

import json

from ..rule_schema import ApprovalReport, MatchedCase, Status

_LABEL = {Status.VIOLATION: "❌ 违规", Status.WARNING: "⚠️ 预警", Status.PASS: "✅ 通过", Status.INSUFFICIENT_INPUT: "➖ 输入不足", Status.ERROR: "⛔ 执行失败"}


def to_json(report: ApprovalReport, indent: int = 2) -> str:
    return json.dumps(report.to_dict(), ensure_ascii=False, indent=indent)


def _pages(start: int, end: int) -> str:
    return str(start) if start == end else f"{start}-{end}"


def to_markdown(report: ApprovalReport, case: MatchedCase) -> str:
    rules = {rule.rule_id: rule for rule in case.rules}
    summary = report.to_dict()["summary"]
    lines = [f"# 招标文件审批报告：{report.source_file}", "", f"**总体结论：{report.overall}**", "", f"违规 {summary['violation']} · 预警 {summary['warning']} · 通过 {summary['pass']} · 输入不足 {summary['insufficient_input']} · 执行失败 {summary['error']}", ""]
    for run in report.rules:
        rule = rules[run.rule_id]
        result = run.result
        label = _LABEL[result.status] if result else "⛔ 无结果"
        lines.extend([f"## 规则 {run.rule_id}　{label}", "", rule.rule_raw, "", f"- **检查方式**：{run.check_method}", f"- **执行器**：`{run.executor}`（{'缓存复用' if run.cached else '本次执行'}，模型调用 {run.attempts} 次）"])
        if result:
            lines.append(f"- **结论**：{result.summary}")
            if result.legal_basis:
                lines.append(f"- **法规依据**：{result.legal_basis}")
            if result.confidence is not None:
                lines.append(f"- **置信度**：{result.confidence:.2f}")
            if result.missing_inputs:
                lines.append(f"- **缺失输入**：{'、'.join(result.missing_inputs)}")
            if result.metrics:
                lines.append("- **指标**：" + "，".join(f"{key}={value}" for key, value in result.metrics.items()))
            for finding in result.findings:
                evidence = rule.evidence[finding.evidence_index]
                location = evidence.location
                source_pages = _pages(location.pdf_pages.start, location.pdf_pages.end)
                document = f"，文件内页码{_pages(location.document_pages.start, location.document_pages.end)}" if location.document_pages else ""
                page_label = {"original_pdf": "PDF", "converted_pdf": "转换PDF", "logical_page": "逻辑页"}[location.page_basis]
                lines.append(f"- **证据**：{location.section}（{page_label}第{source_pages}页{document}）：「{finding.quote}」")
                if finding.reason:
                    lines.append(f"  - {finding.reason}")
        if run.review:
            lines.append(f"- **LLM 复核**：{'通过' if run.review.approved else '未通过'} {run.review.feedback}".rstrip())
        if run.error:
            lines.append(f"- **流程错误**：{run.error}")
        lines.append("")
    return "\n".join(lines)
