"""统一入口：自动创建 report_x，运行单文件、目录批量或已有 JSON 审批。"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from dataclasses import replace
from pathlib import Path

from src.cont_match import prepare_case
from src.cont_match.rules import load_policy_rules
from src.dir_extr import SUPPORTED_DOCUMENT_EXTENSIONS, is_supported_document
from src.engine import run_case
from src.rule_check.report import to_json, to_markdown
from src.rule_schema import MatchedCase


_REPORT_DIR_PATTERN = re.compile(r"^report_?(\d+)$")


def _default_output(input_path: Path) -> Path:
    """根据匹配 JSON 位置推导审批报告目录。"""
    if input_path.parent.name == "matched":
        return input_path.parent.parent / "results"
    return input_path.parent / "results"


def _default_cache(input_path: Path) -> Path:
    """把可续跑的判定缓存放在当前 report_x 内。"""
    if input_path.parent.name == "matched":
        return input_path.parent.parent / "decision_cache"
    return input_path.parent / "decision_cache"


def _load_case(input_path: Path, policy_rules_path: str | None = None) -> MatchedCase:
    """读取已有匹配结果；可用当前政策表补齐/更新第三步路由字段而不重跑匹配。"""
    case = MatchedCase.from_json_file(input_path)
    if not policy_rules_path:
        return case
    policies = {rule.rule_id: rule for rule in load_policy_rules(policy_rules_path)}
    missing = [rule.rule_id for rule in case.rules if rule.rule_id not in policies]
    if missing:
        raise ValueError(f"政策规则文件缺少案件中的规则序号: {missing}")
    return replace(case, rules=[replace(rule, check_method=policies[rule.rule_id].check_method, structured_fields=policies[rule.rule_id].structured_fields) for rule in case.rules])


def _build_parser() -> argparse.ArgumentParser:
    """声明单文件、目录批量和已有 JSON 三种运行模式。"""
    parser = argparse.ArgumentParser(description="招标文件智能合规审批")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", help="已有 rules_matched.json；跳过步骤一、二")
    source.add_argument("--one_report_path", help="单个待解析文档路径")
    source.add_argument("--reports_path", help="批量输入目录；递归处理其中所有支持的文档")

    common = parser.add_argument_group("运行范围")
    common.add_argument("--preprocess-only", action="store_true", help="运行步骤一、二并生成 JSON 后停止")
    common.add_argument("--continue-on-error", action="store_true", help="批量模式中单个文档失败后继续处理")

    extraction = parser.add_argument_group("步骤一：目录提取")
    extraction.add_argument("--document-page-1-pdf-page", type=int, help="可选人工覆盖；正文印刷第1页对应的原始/转换 PDF 页，不传时自动检测")
    extraction.add_argument("--max-section-pages", type=int, default=8)

    matching = parser.add_argument_group("步骤二：内容匹配")
    matching.add_argument("--policy-rules", help="政策规则 JSON/XLSX；处理新文档时必填，--input 时可用于刷新检查方式")
    matching.add_argument("--candidate-count", type=int, default=8)
    matching.add_argument("--evidence-count", type=int, default=2)
    matching.add_argument("--minimum-score", type=float, default=0.03)
    matching.add_argument("--use-llm", action="store_true", help="使用当前本地 Qwen3-8B 服务重排匹配候选")
    matching.add_argument("--strict-llm", action="store_true", help="匹配模型调用失败时终止，不降级为字符召回")
    matching.add_argument("--match-workers", type=int, help="步骤二并发重排规则数，默认读取 MATCHING_WORKERS")

    approval = parser.add_argument_group("步骤三：规则校验与审批")
    approval.add_argument("--rules", nargs="*", type=int, help="只执行指定规则序号")
    approval.add_argument("--no-llm-check", "--no-generate", dest="no_llm_check", action="store_true", help="禁用步骤三语义规则的本地 LLM 判定；旧名 --no-generate 仍兼容")
    approval.add_argument("--force-recheck", "--force-regenerate", dest="force_recheck", action="store_true", help="忽略当前判定缓存重新检查，并保留上一版本历史")
    approval.add_argument("--review", action="store_true", help="用第二次本地 LLM 调用复核结果；会降低速度")
    approval.add_argument("--check-cache-dir", "--checker-dir", dest="check_cache_dir", help="案件判定缓存目录；旧名 --checker-dir 仍兼容")
    approval.add_argument("--check-workers", type=int, help="步骤三并发规则数，默认读取 SEMANTIC_WORKERS")
    approval.add_argument("--rollback-rules", nargs="*", type=int, help="将指定规则恢复为判定缓存中的上一版本")
    return parser


def _allocate_report_dir(reports_root: str | Path = "reports") -> Path:
    """扫描既有编号并原子创建下一个 ``report_x`` 目录。"""
    root = Path(reports_root)
    root.mkdir(parents=True, exist_ok=True)
    numbers = []
    for child in root.iterdir():
        match = _REPORT_DIR_PATTERN.fullmatch(child.name) if child.is_dir() else None
        if match:
            numbers.append(int(match.group(1)))
    next_number = max(numbers, default=0) + 1
    while True:
        report_dir = root / f"report_{next_number}"
        try:
            report_dir.mkdir()
        except FileExistsError:
            next_number += 1
        else:
            return report_dir


def _discover_documents(reports_path: str | Path, reports_root: str | Path = "reports") -> list[Path]:
    """递归发现支持的输入文档，并排除自动生成的 reports 输出目录。"""
    source_root = Path(reports_path).expanduser().resolve()
    if not source_root.is_dir():
        raise ValueError(f"批量输入目录不存在: {source_root}")
    output_root = Path(reports_root).resolve()
    documents = []
    for path in source_root.rglob("*"):
        resolved = path.resolve()
        if not path.is_file() or not is_supported_document(path):
            continue
        if resolved == output_root or output_root in resolved.parents:
            continue
        documents.append(resolved)
    return sorted(documents, key=lambda path: str(path).lower())


def _write_report(case: MatchedCase, input_path: Path, args: argparse.Namespace) -> None:
    """执行规则校验流程并写案件级 JSON/Markdown 报告。"""
    cache_dir = Path(args.check_cache_dir) if args.check_cache_dir else _default_cache(input_path)
    report = run_case(case, rule_ids=args.rules, enable_llm=not args.no_llm_check, force_recheck=args.force_recheck, llm_review=args.review, cache_dir=str(cache_dir), max_workers=args.check_workers, rollback_rule_ids=args.rollback_rules)
    output = _default_output(input_path)
    output.mkdir(parents=True, exist_ok=True)
    (output / "summary.json").write_text(to_json(report) + "\n", encoding="utf-8")
    (output / "summary.md").write_text(to_markdown(report, case), encoding="utf-8")
    counts = report.to_dict()["summary"]
    print(f"总体结论: {report.overall} | 违规 {counts['violation']} 预警 {counts['warning']} 执行失败 {counts['error']} 流程错误 {counts['pipeline_error']}")
    print(f"报告已写入: {output / 'summary.json'}, {output / 'summary.md'}")


def _process_document(report_path: str | Path, args: argparse.Namespace, reports_root: str | Path) -> Path:
    """为一个输入文档分配 report_x，复制原文件并运行所选流程。"""
    source_document = Path(report_path).expanduser().resolve()
    if not source_document.is_file():
        raise ValueError(f"待解析文档不存在: {source_document}")
    if not is_supported_document(source_document):
        supported = ", ".join(sorted(SUPPORTED_DOCUMENT_EXTENSIONS))
        raise ValueError(f"不支持的文档格式 {source_document.suffix or '<无扩展名>'}；当前支持: {supported}")

    report_dir = _allocate_report_dir(reports_root)
    staged_document = report_dir / source_document.name
    shutil.copy2(source_document, staged_document)
    matched_path = report_dir / "matched" / "rules_matched.json"
    artifacts_dir = report_dir / "preprocessing"
    print(f"创建案件目录: {report_dir}，输入文件: {source_document}")

    case = prepare_case(case_id=report_dir.name, report_path=staged_document, rules_path=args.policy_rules, output_path=matched_path, artifacts_dir=artifacts_dir, document_page_1_pdf_page=args.document_page_1_pdf_page, max_section_pages=args.max_section_pages, candidate_count=args.candidate_count, evidence_count=args.evidence_count, minimum_score=args.minimum_score, use_llm=args.use_llm, strict_llm=args.strict_llm, match_workers=args.match_workers)
    evidence_count = sum(len(rule.evidence) for rule in case.rules)
    rules_with_evidence = sum(bool(rule.evidence) for rule in case.rules)
    print(f"步骤一、二完成: {matched_path} | 规则 {len(case.rules)} 匹配到原文 {rules_with_evidence} 证据段 {evidence_count}")
    if not args.preprocess_only:
        _write_report(case, matched_path, args)
    return report_dir


def _validate_args(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    if args.input and args.preprocess_only:
        parser.error("--preprocess-only 只适用于 --one_report_path 或 --reports_path")
    if args.input and args.continue_on_error:
        parser.error("--continue-on-error 只适用于 --reports_path")
    if args.one_report_path and args.continue_on_error:
        parser.error("--continue-on-error 只适用于 --reports_path")
    if (args.one_report_path or args.reports_path) and not args.policy_rules:
        parser.error("处理文档时必须提供 --policy-rules")
    if args.strict_llm and not args.use_llm:
        parser.error("--strict-llm 必须与 --use-llm 一起使用")
    if args.no_llm_check and args.review:
        parser.error("--no-llm-check 与 --review 不能同时使用")
    if args.force_recheck and args.rollback_rules:
        parser.error("--force-recheck 与 --rollback-rules 不能同时使用")
    if args.check_workers is not None and args.check_workers < 1:
        parser.error("--check-workers 必须大于 0")
    if args.match_workers is not None and args.match_workers < 1:
        parser.error("--match-workers 必须大于 0")


def main(argv: list[str] | None = None, *, reports_root: str | Path = "reports") -> None:
    """解析参数并运行单文件、目录批量或已有 JSON 审批。"""
    parser = _build_parser()
    args = parser.parse_args(argv)
    _validate_args(args, parser)

    if args.input:
        input_path = Path(args.input)
        _write_report(_load_case(input_path, args.policy_rules), input_path, args)
        return
    if args.one_report_path:
        _process_document(args.one_report_path, args, reports_root)
        return

    documents = _discover_documents(args.reports_path, reports_root)
    if not documents:
        supported = ", ".join(sorted(SUPPORTED_DOCUMENT_EXTENSIONS))
        parser.error(f"--reports_path 下没有可处理文档；当前支持: {supported}")
    failures = []
    for index, document_path in enumerate(documents, start=1):
        print(f"\n[{index}/{len(documents)}] 开始处理: {document_path}")
        try:
            report_dir = _process_document(document_path, args, reports_root)
        except Exception as exc:
            failures.append((document_path, exc))
            print(f"[{index}/{len(documents)}] 处理失败: {document_path}: {exc}", file=sys.stderr)
            if not args.continue_on_error:
                raise
        else:
            print(f"[{index}/{len(documents)}] 处理完成: {report_dir}")
    if failures:
        details = "\n".join(f"- {path}: {exc}" for path, exc in failures)
        raise SystemExit(f"批量处理存在 {len(failures)} 个失败文件:\n{details}")


if __name__ == "__main__":
    main()
