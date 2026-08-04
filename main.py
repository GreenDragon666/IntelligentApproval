"""步骤三运行时入口：对「已准备好的规则输入 JSON」跑合规校验并出报告。

本入口不读 PDF、不做目录/关键词抽取。输入须符合 TenderContext 契约
（见 data/inputs/ 样例 与 docs/ARCHITECTURE.md）。

用法：
    python main.py --input data/inputs/sample_tender.json --out reports/
    python main.py --input data/inputs/sample_tender.json --rules rule_2 rule_4
"""

from __future__ import annotations

import argparse
from pathlib import Path

from src import report as report_mod
from src.engine import run
from src.schema import TenderContext


def main() -> None:
    ap = argparse.ArgumentParser(description="招标文件智能审批 · 步骤三代码校验")
    ap.add_argument("--input", required=True, help="结构化输入 JSON（TenderContext）")
    ap.add_argument("--rules", nargs="*", help="只跑指定规则 id，如 rule_2 rule_4")
    ap.add_argument("--out", default="reports", help="报告输出目录")
    args = ap.parse_args()

    ctx = TenderContext.from_json_file(args.input)
    doc_name = ctx.doc_name or Path(args.input).stem
    rep = run(ctx, doc_name=doc_name, rule_ids=args.rules)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    stem = Path(args.input).stem
    (out / f"{stem}.json").write_text(report_mod.to_json(rep), encoding="utf-8")
    (out / f"{stem}.md").write_text(report_mod.to_markdown(rep), encoding="utf-8")

    print(f"总体结论: {rep.overall.value} | 违规 {len(rep.violations)} 预警 {len(rep.warnings)}")
    print(f"报告已写入: {out}/{stem}.json, {out}/{stem}.md")


if __name__ == "__main__":
    main()
