#!/usr/bin/env python3
"""运行步骤一、二并生成正式 ``rules_matched.json``。"""

from __future__ import annotations

import argparse
from pathlib import Path

from src.preprocess import prepare_case


def parse_args() -> argparse.Namespace:
    """声明步骤一、二 CLI，并校验严格模型模式的参数组合。"""
    parser = argparse.ArgumentParser(
        description="抽取招标 PDF 章节，匹配政策规则，并生成正式案件 JSON"
    )
    parser.add_argument("--case-id", required=True, help="案件编号，例如 report_2")
    parser.add_argument("--pdf", required=True, help="招标文件 PDF")
    parser.add_argument("--rules", required=True, help="政策规则 JSON/XLSX")
    parser.add_argument("--output", required=True, help="输出 rules_matched.json")
    parser.add_argument("--artifacts-dir", help="可选：保存目录、章节、候选匹配和运行清单")
    parser.add_argument("--document-page-1-pdf-page", type=int, help="正文印刷第1页对应的 PDF 物理页，例如 9")
    parser.add_argument("--max-section-pages", type=int, default=8)
    parser.add_argument("--candidate-count", type=int, default=8)
    parser.add_argument("--evidence-count", type=int, default=2)
    parser.add_argument("--minimum-score", type=float, default=0.03)
    parser.add_argument("--use-llm", action="store_true", help="用服务器本地 Qwen3-7B 重排字符级候选")
    parser.add_argument("--strict-llm", action="store_true", help="本地模型调用失败时终止；默认自动降级为无模型匹配")
    args = parser.parse_args()
    if args.strict_llm and not args.use_llm:
        parser.error("--strict-llm 必须与 --use-llm 一起使用")
    return args


def main() -> None:
    """运行预处理总入口并打印规则/evidence 数量摘要。"""
    args = parse_args()
    case = prepare_case(
        case_id=args.case_id,
        pdf_path=args.pdf,
        rules_path=args.rules,
        output_path=args.output,
        artifacts_dir=args.artifacts_dir,
        document_page_1_pdf_page=args.document_page_1_pdf_page,
        max_section_pages=args.max_section_pages,
        candidate_count=args.candidate_count,
        evidence_count=args.evidence_count,
        minimum_score=args.minimum_score,
        use_llm=args.use_llm,
        strict_llm=args.strict_llm,
    )
    evidence_count = sum(len(rule.evidence) for rule in case.rules)
    rules_with_evidence = sum(bool(rule.evidence) for rule in case.rules)
    print(f"已生成: {Path(args.output)}")
    print(f"规则: {len(case.rules)}，匹配到原文: {rules_with_evidence}，证据段: {evidence_count}")


if __name__ == "__main__":
    main()
