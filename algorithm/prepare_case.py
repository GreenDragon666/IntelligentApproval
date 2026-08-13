#!/usr/bin/env python3
"""步骤一、二独立入口：自动创建 report_x 并生成匹配 JSON。"""

from __future__ import annotations

import argparse

from main import main as run_main


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="只运行目录提取和内容匹配")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--one_report_path", help="单个待解析文档路径")
    source.add_argument("--reports_path", help="批量输入目录；递归处理其中所有支持的文档")
    parser.add_argument("--policy-rules", required=True, help="政策规则 JSON/XLSX")
    parser.add_argument("--document-page-1-pdf-page", type=int, help="可选人工覆盖；正文印刷第1页对应的原始/转换 PDF 页，不传时自动检测")
    parser.add_argument("--max-section-pages", type=int, default=8)
    parser.add_argument("--candidate-count", type=int, default=8)
    parser.add_argument("--evidence-count", type=int, default=3, help="每条规则最终保留 evidence 数，最大为3")
    parser.add_argument("--minimum-score", type=float, default=0.03)
    parser.add_argument("--no-embedding", action="store_true", help="仅使用字符 TF-IDF 召回")
    parser.add_argument("--use-llm", action="store_true", help="用服务器本地 Qwen3-8B 重排混合召回候选")
    parser.add_argument("--strict-llm", action="store_true", help="本地模型调用失败时终止")
    parser.add_argument("--match-workers", type=int, help="并发重排规则数，默认读取 MATCHING_WORKERS")
    parser.add_argument("--continue-on-error", action="store_true", help="批量模式中单个文档失败后继续处理")
    return parser


def _main_argv(args: argparse.Namespace) -> list[str]:
    argv = ["--preprocess-only", "--policy-rules", args.policy_rules]
    argv.extend(["--one_report_path", args.one_report_path] if args.one_report_path else ["--reports_path", args.reports_path])
    for value, option in ((args.document_page_1_pdf_page, "--document-page-1-pdf-page"), (args.max_section_pages, "--max-section-pages"), (args.candidate_count, "--candidate-count"), (args.evidence_count, "--evidence-count"), (args.minimum_score, "--minimum-score"), (args.match_workers, "--match-workers")):
        if value is not None:
            argv.extend([option, str(value)])
    for enabled, option in ((args.no_embedding, "--no-embedding"), (args.use_llm, "--use-llm"), (args.strict_llm, "--strict-llm"), (args.continue_on_error, "--continue-on-error")):
        if enabled:
            argv.append(option)
    return argv


def main(argv: list[str] | None = None) -> None:
    args = _build_parser().parse_args(argv)
    run_main(_main_argv(args))


if __name__ == "__main__":
    main()
