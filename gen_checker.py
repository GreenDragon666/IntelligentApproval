"""步骤三编写期入口：对一条规则跑 LangGraph 流水线，由本地模型生成 checker。

需你先手动起本地 vLLM（仓库不自动启动）：
    bash scripts/serve_llm_3b.sh

用法：
    python gen_checker.py --rule rules/rule_4.md --rule-id rule_4 \\
        --test tests/acceptance/rule_4_accept.py
若不传 --test，使用内置的最小验收测试（仅校验可导入并返回 RuleResult）。
"""

from __future__ import annotations

import argparse
from pathlib import Path

from src.codegen.graph import generate_checker

# 最小验收测试：验证生成模块可导入、check 可调用、返回 RuleResult。
# 真实使用应替换为带正/负样例断言的验收测试（放 tests/acceptance/）。
DEFAULT_TEST = '''\
import candidate  # 触发 @register
from src.schema import TenderContext, RuleResult
from src.registry import all_checkers
fns = all_checkers()
assert fns, "未注册任何 checker"
rid = list(fns)[-1]
r = fns[rid](TenderContext(full_text="测试", sections={"项目概况": "测试"}))
assert isinstance(r, RuleResult), f"返回类型错误: {type(r)}"
print("acceptance ok:", rid, r.status)
'''


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rule", required=True, help="规则 Markdown 路径")
    ap.add_argument("--rule-id", required=True)
    ap.add_argument("--test", help="验收测试 .py（子进程执行，退出码0为通过）")
    args = ap.parse_args()

    rule_text = Path(args.rule).read_text(encoding="utf-8")
    test_code = Path(args.test).read_text(encoding="utf-8") if args.test else DEFAULT_TEST

    state = generate_checker(args.rule_id, rule_text, test_code)
    if state.get("success"):
        print(f"✅ 生成成功（{state['attempts']} 次尝试）→ generated_checkers/{args.rule_id}.py")
        print("请人工 review 后并入 src/checkers/。")
    else:
        print(f"❌ {state['attempts']} 次尝试后仍未通过验收测试。最后错误：\n{state.get('error')}")


if __name__ == "__main__":
    main()
