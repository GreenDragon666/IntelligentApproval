"""针对案件 JSON 中的一条规则生成或更新全局 checker。"""

from __future__ import annotations

import argparse

from src.checker_store import CheckerStore, checker_key
from src.codegen.graph import generate_checker
from src.schema import MatchedCase


def main() -> None:
    parser = argparse.ArgumentParser(description="生成单条招标审批 checker")
    parser.add_argument("--input", required=True, help="rules_matched.json 路径")
    parser.add_argument("--rule-id", required=True, type=int, help="规则序号")
    parser.add_argument("--checker-dir", help="全局 checker 缓存目录")
    parser.add_argument("--feedback", default="", help="人工或复核反馈")
    parser.add_argument("--force", action="store_true", help="已有缓存时仍重新生成")
    args = parser.parse_args()

    case = MatchedCase.from_json_file(args.input)
    rule = case.get_rule(args.rule_id)
    store = CheckerStore(args.checker_dir)
    existing_code = store.load(rule) if store.exists(rule) else ""
    if existing_code and not args.force:
        print(f"已存在可复用 checker: {store.code_path(rule)}")
        return

    state = generate_checker(
        rule,
        feedback=args.feedback,
        store_root=str(store.root),
        previous_code=existing_code,
    )
    if state.get("success"):
        print(
            f"生成成功: {checker_key(rule)}，尝试 {state.get('attempts', 0)} 次，"
            f"路径 {state.get('checker_path')}"
        )
    else:
        raise SystemExit(
            f"生成失败，尝试 {state.get('attempts', 0)} 次：{state.get('error', '')}"
        )


if __name__ == "__main__":
    main()
