#!/usr/bin/env python3
"""目录批量入口：递归处理输入目录中的所有支持文档。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from main import main as run_main  # noqa: E402


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="批量运行招标文件完整审批流程")
    parser.add_argument("--reports_path", required=True, help="批量输入目录；递归处理其中所有支持的文档")
    parser.add_argument("--policy-rules", required=True, help="政策规则 JSON/XLSX")
    parser.add_argument("--document-page-1-pdf-page", type=int, help="可选人工覆盖；正文印刷第1页对应的原始/转换 PDF 页，不传时自动检测")
    parser.add_argument("--max-section-pages", type=int, default=8)
    parser.add_argument("--candidate-count", type=int, default=8)
    parser.add_argument("--evidence-count", type=int, default=2)
    parser.add_argument("--minimum-score", type=float, default=0.03)
    parser.add_argument("--use-llm", action="store_true", help="步骤二使用本地模型重排")
    parser.add_argument("--strict-llm", action="store_true", help="步骤二模型失败即终止当前文档")
    parser.add_argument("--match-workers", type=int, help="步骤二并发重排规则数")
    parser.add_argument("--review", action="store_true", help="步骤三启用第二次 LLM 结果复核；会降低速度")
    parser.add_argument("--no-llm-check", "--no-generate", dest="no_llm_check", action="store_true", help="步骤三禁用语义规则的 LLM 判定")
    parser.add_argument("--force-recheck", "--force-regenerate", dest="force_recheck", action="store_true", help="步骤三忽略当前判定缓存重新检查")
    parser.add_argument("--check-cache-dir", "--checker-dir", dest="check_cache_dir", help="案件判定缓存目录")
    parser.add_argument("--check-workers", type=int, help="步骤三并发规则数")
    parser.add_argument("--rollback-rules", nargs="*", type=int, help="恢复指定规则的上一版判定缓存")
    parser.add_argument("--rules", nargs="*", type=int, help="每个案件只执行指定规则序号")
    parser.add_argument("--continue-on-error", action="store_true", help="单个文档失败后继续处理；最终仍返回非零状态")
    return parser


def _main_argv(args: argparse.Namespace) -> list[str]:
    argv = ["--reports_path", args.reports_path, "--policy-rules", args.policy_rules]
    for value, option in ((args.document_page_1_pdf_page, "--document-page-1-pdf-page"), (args.max_section_pages, "--max-section-pages"), (args.candidate_count, "--candidate-count"), (args.evidence_count, "--evidence-count"), (args.minimum_score, "--minimum-score"), (args.match_workers, "--match-workers"), (args.check_cache_dir, "--check-cache-dir"), (args.check_workers, "--check-workers")):
        if value is not None:
            argv.extend([option, str(value)])
    if args.rules:
        argv.append("--rules")
        argv.extend(str(rule_id) for rule_id in args.rules)
    if args.rollback_rules:
        argv.append("--rollback-rules")
        argv.extend(str(rule_id) for rule_id in args.rollback_rules)
    for enabled, option in ((args.use_llm, "--use-llm"), (args.strict_llm, "--strict-llm"), (args.review, "--review"), (args.no_llm_check, "--no-llm-check"), (args.force_recheck, "--force-recheck"), (args.continue_on_error, "--continue-on-error")):
        if enabled:
            argv.append(option)
    return argv


def main(argv: list[str] | None = None) -> None:
    args = _build_parser().parse_args(argv)
    run_main(_main_argv(args))


if __name__ == "__main__":
    main()
