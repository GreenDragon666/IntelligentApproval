"""案件审批报告的 JSON 与 Markdown 渲染。"""

from __future__ import annotations

import json
from collections.abc import Sequence

from ..rule_schema import ApprovalReport, MatchedCase, Status

_LABEL = {Status.VIOLATION: "❌ 违规", Status.WARNING: "⚠️ 预警", Status.PASS: "✅ 通过", Status.INSUFFICIENT_INPUT: "➖ 输入不足", Status.ERROR: "⛔ 执行失败"}
_OVERALL_LABEL = {"violation": "违规", "warning": "预警", "pass": "通过", "partial": "部分完成"}


def to_json(report: ApprovalReport, indent: int = 2) -> str:
    return json.dumps(report.to_dict(), ensure_ascii=False, indent=indent)


def _pages(start: int, end: int) -> str:
    return str(start) if start == end else f"{start}-{end}"


def _location_text(evidence) -> str:
    location = evidence.location
    source_pages = _pages(location.pdf_pages.start, location.pdf_pages.end)
    document = f"，文件内页码{_pages(location.document_pages.start, location.document_pages.end)}" if location.document_pages else ""
    page_label = {"original_pdf": "PDF", "converted_pdf": "转换PDF", "logical_page": "逻辑页"}[location.page_basis]
    return f"{location.file} · {location.section}（{page_label}第{source_pages}页{document}）"


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
            if result.analysis:
                lines.append(f"- **LLM 分析**：{result.analysis}")
            if result.legal_basis:
                lines.append(f"- **法规依据**：{result.legal_basis}")
            if result.confidence is not None:
                lines.append(f"- **置信度**：{result.confidence:.2f}")
            if result.missing_inputs:
                lines.append(f"- **缺失输入**：{'、'.join(result.missing_inputs)}")
            if result.metrics:
                lines.append("- **指标**：" + "，".join(f"{key}={value}" for key, value in result.metrics.items()))
            if rule.evidence:
                locations = list(dict.fromkeys(_location_text(evidence) for evidence in rule.evidence))
                lines.append(f"- **证据位置**：{'；'.join(locations)}")
            for finding in result.findings:
                evidence = rule.evidence[finding.evidence_index]
                lines.append(f"- **命中原文**：{_location_text(evidence)}：「{finding.quote}」")
                if finding.reason:
                    lines.append(f"  - {finding.reason}")
        if run.review:
            lines.append(f"- **LLM 复核**：{'通过' if run.review.approved else '未通过'} {run.review.feedback}".rstrip())
        if run.error:
            lines.append(f"- **流程错误**：{run.error}")
        lines.append("")
    return "\n".join(lines)


def _escape_table(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _status_rules(report: ApprovalReport, status: Status) -> list[str]:
    return [f"规则 {run.rule_id}：{run.rule_raw}" for run in report.rules if run.result and run.result.status == status]


def _rule_list(lines: list[str], title: str, values: list[str]) -> None:
    lines.extend([f"### {title}（{len(values)}）", ""])
    if values:
        lines.extend(f"- {value}" for value in values)
    else:
        lines.append("- 无")
    lines.append("")


def to_brief_markdown(reports: Sequence[ApprovalReport], failures: Sequence[tuple[str, str]] = ()) -> str:
    """渲染一次完整运行的执法简报；批量时所有案件只写一个文件。"""
    totals = {status.value: 0 for status in Status}
    pipeline_errors = 0
    for report in reports:
        summary = report.to_dict()["summary"]
        for status in Status:
            totals[status.value] += int(summary[status.value])
        pipeline_errors += int(summary["pipeline_error"])
    lines = ["# 招标文件审批执法简报", "", f"本次完成校验 **{len(reports)}** 份文件，处理失败 **{len(failures)}** 份。", "", f"规则结果合计：通过 **{totals['pass']}**，预警 **{totals['warning']}**，违规 **{totals['violation']}**，输入不足 **{totals['insufficient_input']}**，执行失败 **{totals['error']}**，流程错误 **{pipeline_errors}**。", "", "## 文件概览", "", "| 招标文件 | 总体结论 | 通过 | 预警 | 违规 | 输入不足 | 执行失败 |", "|---|---:|---:|---:|---:|---:|---:|"]
    for report in reports:
        summary = report.to_dict()["summary"]
        lines.append(f"| {_escape_table(report.source_file)} | {_OVERALL_LABEL.get(report.overall, report.overall)} | {summary['pass']} | {summary['warning']} | {summary['violation']} | {summary['insufficient_input']} | {summary['error']} |")
    if not reports:
        lines.append("| 无成功完成的文件 | - | 0 | 0 | 0 | 0 | 0 |")
    lines.append("")
    for report in reports:
        lines.extend([f"## {_escape_table(report.source_file)}", ""])
        _rule_list(lines, "通过规则", _status_rules(report, Status.PASS))
        _rule_list(lines, "预警规则", _status_rules(report, Status.WARNING))
        _rule_list(lines, "违规规则", _status_rules(report, Status.VIOLATION))
        incomplete = _status_rules(report, Status.INSUFFICIENT_INPUT) + _status_rules(report, Status.ERROR)
        _rule_list(lines, "未完成自动判断的规则", incomplete)
    if failures:
        lines.extend(["## 处理失败的文件", ""])
        for file_name, error in failures:
            lines.append(f"- **{file_name}**：{error}")
        lines.append("")
    return "\n".join(lines)
