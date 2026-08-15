"""Translate algorithm-native reports into the stable frontend API contract.

This module deliberately uses only Python standard-library types. It is the
anti-corruption layer between the evolving algorithm JSON and the public API.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping


PUBLIC_STATUSES = ("violation", "warning", "insufficient", "passed")


@dataclass(frozen=True)
class DocumentProjection:
    document_id: str
    file_name: str
    status: str
    detail: dict[str, Any] | None
    execution_failed: int = 0
    error_message: str | None = None


def _public_status(value: object) -> str:
    aliases = {
        "violation": "violation",
        "warning": "warning",
        "pass": "passed",
        "passed": "passed",
        "insufficient_input": "insufficient",
        "insufficient": "insufficient",
        "error": "insufficient",
        "partial": "insufficient",
    }
    return aliases.get(str(value or ""), "insufficient")


def _overall(counts: Mapping[str, int]) -> str:
    if counts.get("violation", 0):
        return "violation"
    if counts.get("warning", 0):
        return "warning"
    if counts.get("insufficient", 0):
        return "insufficient"
    return "passed"


def _page_range(value: object) -> str:
    data = value if isinstance(value, Mapping) else {}
    start = data.get("start")
    end = data.get("end")
    if not isinstance(start, int) or not isinstance(end, int):
        return ""
    return str(start) if start == end else f"{start}-{end}"


def _location(evidence: Mapping[str, Any]) -> str:
    location = evidence.get("location")
    location = location if isinstance(location, Mapping) else {}
    file_name = str(location.get("file") or "未知文件")
    section = str(location.get("section") or "未知章节")
    pages = _page_range(location.get("pdf_pages"))
    basis = {
        "original_pdf": "PDF",
        "converted_pdf": "转换PDF",
        "logical_page": "逻辑页",
    }.get(str(location.get("page_basis") or ""), "页")
    source = f"{basis}第{pages}页" if pages else "页码未知"
    document_pages = _page_range(location.get("document_pages"))
    document = f"，文件内页码{document_pages}" if document_pages else ""
    return f"{file_name} · {section}（{source}{document}）"


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _indicators(metrics: object) -> dict[str, Any] | None:
    data = metrics if isinstance(metrics, Mapping) else {}
    indicators: dict[str, Any] = {}
    if isinstance(data.get("requires_review"), bool):
        indicators["requiresReview"] = data["requires_review"]
    unresolved = _strings(data.get("unresolved_fields"))
    if unresolved:
        indicators["unresolvedFields"] = unresolved
    evaluated = data.get("evaluated_subchecks", data.get("evaluated_checks"))
    if isinstance(evaluated, int) and not isinstance(evaluated, bool):
        indicators["evaluatedSubchecks"] = max(0, evaluated)
    aliases = _strings(data.get("semantic_field_aliases", data.get("resolved_fields")))
    if aliases:
        indicators["fieldAliases"] = aliases
    return indicators or None


def _matched_text(findings: object, evidence: list[Mapping[str, Any]]) -> str | None:
    if not isinstance(findings, list):
        return None
    blocks: list[str] = []
    for finding in findings:
        if not isinstance(finding, Mapping):
            continue
        index = finding.get("evidence_index")
        source = _location(evidence[index]) if isinstance(index, int) and 0 <= index < len(evidence) else "证据位置未知"
        quote = _text(finding.get("quote"))
        reason = _text(finding.get("reason"))
        if quote:
            block = f"{source}：「{quote}」"
            if reason:
                block += f"\n- {reason}"
            blocks.append(block)
    return "\n\n".join(blocks) or None


def map_document_detail(*, review_id: str, document_id: str, file_name: str, report: Mapping[str, Any], matched_case: Mapping[str, Any]) -> tuple[dict[str, Any], int]:
    matched_rules = {
        item.get("rule_id"): item
        for item in matched_case.get("rules", [])
        if isinstance(item, Mapping) and isinstance(item.get("rule_id"), int)
    }
    details: list[dict[str, Any]] = []
    execution_failed = 0
    for run in report.get("rules", []):
        if not isinstance(run, Mapping):
            continue
        rule_id = run.get("rule_id")
        if not isinstance(rule_id, int):
            continue
        rule = matched_rules.get(rule_id, {})
        evidence = [item for item in rule.get("evidence", []) if isinstance(item, Mapping)] if isinstance(rule, Mapping) else []
        result = run.get("result")
        result = result if isinstance(result, Mapping) else {}
        algorithm_status = str(result.get("status") or "error")
        if algorithm_status == "error":
            execution_failed += 1
        detail: dict[str, Any] = {
            "id": f"rule-{rule_id}",
            "number": rule_id,
            "title": str(rule.get("rule_raw") or run.get("rule_raw") or f"规则 {rule_id}"),
            "status": _public_status(algorithm_status),
        }
        optional = {
            "conclusion": _text(result.get("summary")),
            "llmAnalysis": _text(result.get("analysis")),
            "legalBasis": _text(result.get("legal_basis")),
            "evidenceLocations": "；".join(dict.fromkeys(_location(item) for item in evidence)) or None,
            "matchedText": _matched_text(result.get("findings"), evidence),
            "missingInputs": "、".join(_strings(result.get("missing_inputs"))) or None,
            "confidence": result.get("confidence") if isinstance(result.get("confidence"), (int, float)) else None,
            "indicators": _indicators(result.get("metrics")),
        }
        if algorithm_status == "error" and not optional["missingInputs"]:
            optional["missingInputs"] = "自动校验执行失败，请由管理员查看该文件的算法日志"
        detail.update({key: value for key, value in optional.items() if value is not None})
        details.append(detail)

    counts = {status: sum(item["status"] == status for item in details) for status in PUBLIC_STATUSES}
    return {
        "schemaVersion": "1.0",
        "reviewId": review_id,
        "documentId": document_id,
        "fileName": file_name,
        "overallConclusion": _overall(counts),
        "rules": details,
    }, execution_failed


def _failed_detail(review_id: str, document: DocumentProjection) -> dict[str, Any]:
    return {
        "schemaVersion": "1.0",
        "reviewId": review_id,
        "documentId": document.document_id,
        "fileName": document.file_name,
        "overallConclusion": "insufficient",
        "rules": [],
    }


def build_review_summary(review_id: str, documents: Iterable[DocumentProjection]) -> dict[str, Any]:
    projections = list(documents)
    document_items: list[dict[str, Any]] = []
    totals = {status: 0 for status in PUBLIC_STATUSES}
    execution_failed_count = 0
    for document in projections:
        detail = document.detail or _failed_detail(review_id, document)
        rules = detail.get("rules") if isinstance(detail.get("rules"), list) else []
        counts = {status: sum(isinstance(rule, Mapping) and rule.get("status") == status for rule in rules) for status in PUBLIC_STATUSES}
        for status, count in counts.items():
            totals[status] += count
        execution_failed_count += document.execution_failed
        document_items.append({
            "id": document.document_id,
            "fileName": document.file_name,
            "overallConclusion": detail.get("overallConclusion", "insufficient"),
            "counts": {**counts, "executionFailed": document.execution_failed},
            "rules": [
                {key: rule[key] for key in ("id", "number", "title", "status") if key in rule}
                for rule in rules if isinstance(rule, Mapping)
            ],
            "detailAvailable": document.status == "completed" and bool(rules),
        })
    completed = sum(document.status == "completed" for document in projections)
    failed = sum(document.status == "failed" for document in projections)
    valid = sum(totals.values()) - execution_failed_count
    return {
        "schemaVersion": "1.0",
        "reviewId": review_id,
        "mode": "live",
        "sourceFiles": [document.file_name for document in projections],
        "overallConclusion": _overall(totals) if totals and sum(totals.values()) else "insufficient",
        "completedDocuments": completed,
        "failedDocuments": failed,
        "validDecisionCount": max(0, valid),
        "executionFailedCount": execution_failed_count,
        "counts": totals,
        "documents": document_items,
    }
