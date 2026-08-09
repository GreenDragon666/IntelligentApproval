"""步骤一、二总入口：PDF → 章节 → 规则匹配 → 正式案件 JSON。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..rule_schema import (
    EvidenceLocation,
    MatchedCase,
    MatchedEvidence,
    MatchedRule,
    PageRange,
    SourceDocument,
)
from .llm_matcher import select_candidates
from .page_schema import DocumentSection, SectionCandidate
from .pdf import extract_pdf_outline, extract_pdf_pages
from .retrieval import LexicalSectionMatcher
from .rules import load_policy_rules
from .sections import split_sections


def _write_json(path: Path, data: Any) -> None:
    """统一以 UTF-8、中文不转义和缩进格式写 JSON。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _to_evidence(section: DocumentSection, source_file: str) -> MatchedEvidence:
    """把内部章节转换为正式 evidence，映射文件名和双页码。"""
    document_pages = None
    if section.document_start is not None and section.document_end is not None:
        document_pages = PageRange(section.document_start, section.document_end)
    return MatchedEvidence(
        location=EvidenceLocation(
            file=source_file,
            section=section.title,
            pdf_pages=PageRange(section.pdf_start, section.pdf_end),
            document_pages=document_pages,
        ),
        text=section.text,
    )


def _lexical_selection(
    candidates: list[SectionCandidate],
    *,
    evidence_count: int,
    minimum_score: float,
) -> list[SectionCandidate]:
    """无模型或模型降级时按阈值选择前 N 个字符召回候选。"""
    return [
        candidate
        for candidate in candidates
        if candidate.score >= minimum_score
    ][:evidence_count]


def prepare_case(
    *,
    case_id: str,
    pdf_path: str | Path,
    rules_path: str | Path,
    output_path: str | Path,
    artifacts_dir: str | Path | None = None,
    document_page_1_pdf_page: int | None = None,
    max_section_pages: int = 8,
    candidate_count: int = 8,
    evidence_count: int = 2,
    minimum_score: float = 0.03,
    use_llm: bool = False,
    strict_llm: bool = False,
) -> MatchedCase:
    """生成可直接交给 ``main.py`` 的正式 ``rules_matched.json``。

    ``use_llm=False`` 时全程不访问模型，直接采用字符级召回结果。启用 LLM 后，
    本地 Qwen 只对 top-k 候选重排；调用失败时默认降级到字符级结果，只有
    ``strict_llm=True`` 才中止任务。
    """

    if not case_id.strip():
        raise ValueError("case_id 不能为空")
    if candidate_count < 1 or evidence_count < 1:
        raise ValueError("candidate_count 和 evidence_count 必须大于 0")
    if evidence_count > candidate_count:
        raise ValueError("evidence_count 不得大于 candidate_count")
    if minimum_score < 0:
        raise ValueError("minimum_score 不得小于 0")

    pdf = Path(pdf_path)
    output = Path(output_path)
    source_file = pdf.name
    pages = extract_pdf_pages(
        pdf,
        document_page_1_pdf_page=document_page_1_pdf_page,
    )
    if not any(page.text for page in pages):
        raise ValueError("PDF 没有可提取文本，可能是扫描件；当前流程尚未配置 OCR")
    outline = extract_pdf_outline(pdf)
    sections = split_sections(
        pages,
        outline=outline,
        max_pages=max_section_pages,
    )
    if not sections:
        raise ValueError("PDF 未生成可匹配章节")

    policy_rules = load_policy_rules(rules_path)
    matcher = LexicalSectionMatcher(sections)
    matched_rules: list[MatchedRule] = []
    match_artifacts: list[dict[str, Any]] = []

    for rule in policy_rules:
        candidates = matcher.rank(rule, top_k=candidate_count)
        selected = _lexical_selection(
            candidates,
            evidence_count=evidence_count,
            minimum_score=minimum_score,
        )
        selection_method = "lexical"
        llm_error = ""
        if use_llm and candidates:
            try:
                selected = select_candidates(
                    rule,
                    candidates,
                    max_selected=evidence_count,
                )
                selection_method = "local_qwen"
            except Exception as exc:
                llm_error = f"{type(exc).__name__}: {exc}"
                if strict_llm:
                    raise RuntimeError(
                        f"规则 {rule.rule_id} 的本地 LLM 匹配失败: {llm_error}"
                    ) from exc
                selection_method = "lexical_fallback"

        matched_rules.append(
            MatchedRule(
                rule_id=rule.rule_id,
                rule_raw=rule.rule_raw,
                rule_text=rule.rule_text,
                evidence=[
                    _to_evidence(candidate.section, source_file)
                    for candidate in selected
                ],
            )
        )
        artifact: dict[str, Any] = {
            "rule_id": rule.rule_id,
            "rule_raw": rule.rule_raw,
            "selection_method": selection_method,
            "candidates": [candidate.to_dict() for candidate in candidates],
            "selected": [candidate.to_dict() for candidate in selected],
        }
        if llm_error:
            artifact["llm_error"] = llm_error
        match_artifacts.append(artifact)

    case = MatchedCase(
        case_id=case_id.strip(),
        source=SourceDocument(file=source_file),
        rules=matched_rules,
    )
    _write_json(output, case.to_dict())

    if artifacts_dir is not None:
        artifacts = Path(artifacts_dir)
        _write_json(
            artifacts / "outline.json",
            [
                {"level": level, "title": title, "pdf_page": pdf_page}
                for level, title, pdf_page in outline
            ],
        )
        _write_json(artifacts / "sections.json", [section.to_dict() for section in sections])
        _write_json(artifacts / "matches.json", match_artifacts)
        _write_json(
            artifacts / "manifest.json",
            {
                "case_id": case.case_id,
                "source_file": source_file,
                "rules_file": str(Path(rules_path)),
                "pdf_page_count": len(pages),
                "outline_count": len(outline),
                "section_source": "pdf_outline" if outline else "heading_heuristic",
                "section_count": len(sections),
                "rule_count": len(policy_rules),
                "rules_with_evidence": sum(bool(rule.evidence) for rule in matched_rules),
                "document_page_1_pdf_page": document_page_1_pdf_page,
                "use_llm": use_llm,
                "strict_llm": strict_llm,
                "candidate_count": candidate_count,
                "evidence_count": evidence_count,
                "minimum_score": minimum_score,
                "output": str(output),
            },
        )
    return case
