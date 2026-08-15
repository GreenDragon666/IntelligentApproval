"""Create run-level report files from the public summary contract."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any, Mapping


_LABEL = {"violation": "违规", "warning": "预警", "insufficient": "输入不足", "passed": "通过"}


def _escape(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def render_brief(summary: Mapping[str, Any]) -> str:
    counts = summary.get("counts") if isinstance(summary.get("counts"), Mapping) else {}
    lines = [
        "# 招标文件审批执法简报",
        "",
        f"审查任务：`{summary.get('reviewId', '')}`",
        "",
        f"本次完成校验 **{summary.get('completedDocuments', 0)}** 份文件，处理失败 **{summary.get('failedDocuments', 0)}** 份。",
        "",
        f"规则结果合计：通过 **{counts.get('passed', 0)}**，预警 **{counts.get('warning', 0)}**，违规 **{counts.get('violation', 0)}**，输入不足 **{counts.get('insufficient', 0)}**，执行失败 **{summary.get('executionFailedCount', 0)}**。",
        "",
        "## 文件概览",
        "",
        "| 招标文件 | 总体结论 | 通过 | 预警 | 违规 | 输入不足 | 执行失败 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for document in summary.get("documents", []):
        if not isinstance(document, Mapping):
            continue
        doc_counts = document.get("counts") if isinstance(document.get("counts"), Mapping) else {}
        lines.append(
            f"| {_escape(document.get('fileName', ''))} | {_LABEL.get(str(document.get('overallConclusion')), document.get('overallConclusion', ''))} | "
            f"{doc_counts.get('passed', 0)} | {doc_counts.get('warning', 0)} | {doc_counts.get('violation', 0)} | "
            f"{doc_counts.get('insufficient', 0)} | {doc_counts.get('executionFailed', 0)} |"
        )
    lines.append("")
    for document in summary.get("documents", []):
        if not isinstance(document, Mapping):
            continue
        lines.extend([f"## {_escape(document.get('fileName', ''))}", ""])
        rules = [rule for rule in document.get("rules", []) if isinstance(rule, Mapping)]
        for status in ("violation", "warning", "insufficient", "passed"):
            selected = [rule for rule in rules if rule.get("status") == status]
            lines.extend([f"### {_LABEL[status]}规则（{len(selected)}）", ""])
            lines.extend(f"- 规则 {rule.get('number')}：{rule.get('title')}" for rule in selected)
            if not selected:
                lines.append("- 无")
            lines.append("")
    return "\n".join(lines)


def write_review_files(review_path: Path, summary: dict[str, Any]) -> tuple[Path, Path]:
    review_path.mkdir(parents=True, exist_ok=True)
    json_path = review_path / "summary.json"
    markdown_path = review_path / "summary_brief.md"
    _atomic_write(json_path, json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    _atomic_write(markdown_path, render_brief(summary) + "\n")
    return json_path, markdown_path


def _atomic_write(path: Path, content: str) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
