"""步骤二生产入口：调用多格式文档提取、执行规则匹配并输出正式 JSON。"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from config import settings
from ..rule_schema import (
    EvidenceLocation,
    MatchedCase,
    MatchedEvidence,
    MatchedRule,
    PageRange,
    SourceDocument,
)
from ..dir_extr import extract_document, split_sections
from ..page_schema import DocumentSection, SectionCandidate
from .llm_matcher import select_candidates
from .retrieval import HybridSectionMatcher, LexicalSectionMatcher
from .rules import load_policy_rules

MAX_EVIDENCE_COUNT = 3


def _write_json(path: Path, data: Any) -> None:
    """统一以 UTF-8、中文不转义和缩进格式写 JSON。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _to_evidence(section: DocumentSection, source_file: str, page_basis: str) -> MatchedEvidence:
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
            page_basis=page_basis,
        ),
        text=section.text,
    )


def _retrieval_selection(
    candidates: list[SectionCandidate],
    *,
    evidence_count: int,
    minimum_score: float,
) -> list[SectionCandidate]:
    """无重排或模型降级时按融合分数阈值选择前 N 个召回候选。"""
    return [
        candidate
        for candidate in candidates
        if candidate.score >= minimum_score
    ][:evidence_count]


def prepare_case(
    *,
    case_id: str,
    report_path: str | Path,
    rules_path: str | Path,
    output_path: str | Path,
    artifacts_dir: str | Path | None = None,
    document_page_1_pdf_page: int | None = None,
    max_section_pages: int = 8,
    candidate_count: int = 8,
    evidence_count: int = MAX_EVIDENCE_COUNT,
    minimum_score: float = 0.03,
    use_embedding: bool = True,
    use_llm: bool = False,
    strict_llm: bool = False,
    match_workers: int | None = None,
) -> MatchedCase:
    """生成可直接交给 ``main.py`` 的正式 ``rules_matched.json``。

    默认先融合字符 TF-IDF 与本地 embedding；``use_embedding=False`` 时只用字符召回。
    启用 LLM 后，本地 Qwen 只对 top-k 候选重排；调用失败时默认降级到召回结果，只有
    ``strict_llm=True`` 才中止任务。
    """

    if not case_id.strip():
        raise ValueError("case_id 不能为空")
    if candidate_count < 1 or evidence_count < 1:
        raise ValueError("candidate_count 和 evidence_count 必须大于 0")
    if evidence_count > candidate_count:
        raise ValueError("evidence_count 不得大于 candidate_count")
    if evidence_count > MAX_EVIDENCE_COUNT:
        raise ValueError(f"evidence_count 最大为 {MAX_EVIDENCE_COUNT}")
    if minimum_score < 0:
        raise ValueError("minimum_score 不得小于 0")
    if match_workers is not None and match_workers < 1:
        raise ValueError("match_workers 必须大于 0")

    report = Path(report_path)
    output = Path(output_path)
    source_file = report.name
    artifacts = Path(artifacts_dir) if artifacts_dir is not None else None
    converted_pdf_path = artifacts / "converted_source.pdf" if artifacts is not None else None
    extracted = extract_document(report, document_page_1_pdf_page=document_page_1_pdf_page, converted_pdf_output=converted_pdf_path)
    pages = extracted.pages
    if not any(page.text for page in pages):
        raise ValueError("文档没有可提取文本；若为扫描件，当前流程尚未配置 OCR")
    outline = extracted.outline
    sections = split_sections(
        pages,
        outline=outline,
        max_pages=max_section_pages,
    )
    if not sections:
        raise ValueError("文档未生成可匹配章节")

    policy_rules = load_policy_rules(rules_path)
    matched_rules: list[MatchedRule] = []
    match_artifacts: list[dict[str, Any]] = []

    embedding_error = ""
    if use_embedding:
        try:
            hybrid_ranked = HybridSectionMatcher(sections).rank_all(policy_rules, top_k=candidate_count)
        except Exception as exc:
            embedding_error = f"{type(exc).__name__}: {exc}"
            if settings.embed_strict:
                raise RuntimeError(f"步骤二 embedding 召回失败: {embedding_error}") from exc
            print(f"步骤二 embedding 不可用，已降级为字符召回: {embedding_error}", flush=True)
            matcher = LexicalSectionMatcher(sections)
            ranked = [(rule, matcher.rank(rule, top_k=candidate_count)) for rule in policy_rules]
        else:
            ranked = list(zip(policy_rules, hybrid_ranked))
    else:
        matcher = LexicalSectionMatcher(sections)
        ranked = [(rule, matcher.rank(rule, top_k=candidate_count)) for rule in policy_rules]
    retrieval_method = "hybrid" if use_embedding and not embedding_error else "lexical"
    selections: dict[int, tuple[list[SectionCandidate], str, str]] = {}
    for rule, candidates in ranked:
        selections[rule.rule_id] = (_retrieval_selection(candidates, evidence_count=evidence_count, minimum_score=minimum_score), retrieval_method, "")
    if use_llm:
        workers = max(1, match_workers or settings.matching_workers)
        errors: list[tuple[int, Exception]] = []
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="content-match") as pool:
            futures = {pool.submit(select_candidates, rule, candidates, max_selected=evidence_count): (rule, candidates) for rule, candidates in ranked if candidates}
            total = len(futures)
            completed = 0
            for future in as_completed(futures):
                rule, candidates = futures[future]
                try:
                    selected = future.result()
                    if selected:
                        selections[rule.rule_id] = (selected, f"local_qwen_{retrieval_method}", "")
                    else:
                        previous, _method, _error = selections[rule.rule_id]
                        # Qwen 的“全部拒绝”不能抹掉第一阶段已经达到阈值的候选。
                        # 保留第一阶段召回证据，交给步骤三结合 rule_raw 再判断。
                        selections[rule.rule_id] = (previous, f"local_qwen_empty_{retrieval_method}_fallback", "")
                except Exception as exc:
                    llm_error = f"{type(exc).__name__}: {exc}"
                    previous, _method, _error = selections[rule.rule_id]
                    selections[rule.rule_id] = (previous, f"{retrieval_method}_fallback", llm_error)
                    errors.append((rule.rule_id, exc))
                completed += 1
                interval = max(1, total // 10)
                if completed == total or completed % interval == 0:
                    print(f"步骤二 LLM 重排进度: {completed}/{total}", flush=True)
        if strict_llm and errors:
            rule_id, exc = sorted(errors, key=lambda item: item[0])[0]
            raise RuntimeError(f"规则 {rule_id} 的本地 LLM 匹配失败: {type(exc).__name__}: {exc}") from exc

    for rule, candidates in ranked:
        selected, selection_method, llm_error = selections[rule.rule_id]
        selected = selected[:min(evidence_count, MAX_EVIDENCE_COUNT)]

        matched_rules.append(
            MatchedRule(
                rule_id=rule.rule_id,
                rule_raw=rule.rule_raw,
                rule_text=rule.rule_text,
                check_method=rule.check_method,
                structured_fields=rule.structured_fields,
                evidence=[
                    _to_evidence(candidate.section, source_file, extracted.page_basis)
                    for candidate in selected
                ],
            )
        )
        artifact: dict[str, Any] = {
            "rule_id": rule.rule_id,
            "rule_raw": rule.rule_raw,
            "check_method": rule.check_method,
            "structured_fields": rule.structured_fields,
            "selection_method": selection_method,
            "candidates": [candidate.to_dict() for candidate in candidates],
            "selected": [candidate.to_dict() for candidate in selected],
        }
        if llm_error:
            artifact["llm_error"] = llm_error
        if embedding_error:
            artifact["embedding_error"] = embedding_error
        match_artifacts.append(artifact)

    case = MatchedCase(
        case_id=case_id.strip(),
        source=SourceDocument(file=source_file),
        rules=matched_rules,
    )
    _write_json(output, case.to_dict())

    if artifacts is not None:
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
                "source_format": extracted.source_format,
                "extraction_method": extracted.extraction_method,
                "page_basis": extracted.page_basis,
                "converted_pdf_file": str(converted_pdf_path) if converted_pdf_path is not None and converted_pdf_path.is_file() else None,
                "rules_file": str(Path(rules_path)),
                "pdf_page_count": len(pages),
                "source_page_count": len(pages),
                "outline_count": len(outline),
                "section_source": "document_outline" if outline else "heading_heuristic",
                "section_count": len(sections),
                "rule_count": len(policy_rules),
                "rules_with_evidence": sum(bool(rule.evidence) for rule in matched_rules),
                "document_page_1_pdf_page": extracted.document_page_1_pdf_page,
                "page_number_detection": (
                    extracted.page_number_detection.to_dict() if extracted.page_number_detection else None
                ),
                "use_llm": use_llm,
                "use_embedding": use_embedding,
                "retrieval_method": retrieval_method,
                "embedding_model": settings.embed_model if use_embedding else None,
                "embedding_error": embedding_error or None,
                "strict_llm": strict_llm,
                "candidate_count": candidate_count,
                "evidence_count": evidence_count,
                "minimum_score": minimum_score,
                "match_workers": match_workers or settings.matching_workers,
                "output": str(output),
            },
        )
    return case
