"""案件级入口：读取 rules_matched.json，生成/复用 checker 并输出报告。"""

from __future__ import annotations

import argparse
from pathlib import Path

from src.engine import run_case
from src.report import to_json, to_markdown
from src.schema import MatchedCase


def _default_output(input_path: Path) -> Path:
    if input_path.parent.name == "matched":
        return input_path.parent.parent / "results"
    return input_path.parent / "results"


def main() -> None:
    parser = argparse.ArgumentParser(description="招标文件智能合规审批")
    parser.add_argument("--input", required=True, help="rules_matched.json 路径")
    parser.add_argument("--rules", nargs="*", type=int, help="只执行指定规则序号")
    parser.add_argument("--out", help="输出目录；默认在案件目录的 results/")
    parser.add_argument(
        "--no-generate",
        action="store_true",
        help="缺少 checker 时不调用本地模型，适合无模型环境",
    )
    parser.add_argument("--force-regenerate", action="store_true", help="忽略缓存重新生成")
    parser.add_argument("--review", action="store_true", help="用本地 LLM 复核结果并反馈迭代")
    parser.add_argument("--checker-dir", help="全局 checker 缓存目录")
    args = parser.parse_args()
    if args.no_generate and args.force_regenerate:
        parser.error("--no-generate 与 --force-regenerate 不能同时使用")

    input_path = Path(args.input)
    case = MatchedCase.from_json_file(input_path)
    report = run_case(
        case,
        rule_ids=args.rules,
        generate_missing=not args.no_generate,
        force_regenerate=args.force_regenerate,
        llm_review=args.review,
        checker_dir=args.checker_dir,
    )

    output = Path(args.out) if args.out else _default_output(input_path)
    output.mkdir(parents=True, exist_ok=True)
    (output / "summary.json").write_text(to_json(report) + "\n", encoding="utf-8")
    (output / "summary.md").write_text(to_markdown(report, case), encoding="utf-8")
    counts = report.to_dict()["summary"]
    print(
        f"总体结论: {report.overall} | 违规 {counts['violation']} "
        f"预警 {counts['warning']} 执行失败 {counts['error']} "
        f"流程错误 {counts['pipeline_error']}"
    )
    print(f"报告已写入: {output / 'summary.json'}, {output / 'summary.md'}")


if __name__ == "__main__":
    main()
