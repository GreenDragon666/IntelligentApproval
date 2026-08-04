"""步骤三编写期：LangGraph 代码生成流水线。

图结构：
    generate ──> validate ──(pass)──> save ──> END
                    │
                    └──(fail & 还有重试次数)──> generate（带错误反馈）

需本机已手动启动 vLLM（scripts/serve_llm_3b.sh）。langgraph/openai 懒加载。
"""

from __future__ import annotations

from pathlib import Path
from typing import TypedDict

from config import settings
from .. import llm
from . import prompts
from .sandbox import extract_code, run_checker_test


class CodegenState(TypedDict, total=False):
    rule_id: str
    rule_text: str
    test_code: str        # 该规则的验收测试（人工提供，作为生成正确性的锚点）
    code: str
    error: str
    attempts: int
    success: bool


def _node_generate(state: CodegenState) -> CodegenState:
    if state.get("attempts", 0) == 0:
        prompt = prompts.build_generate_prompt(state["rule_id"], state["rule_text"])
    else:
        prompt = prompts.build_retry_prompt(state["rule_id"], state.get("code", ""), state.get("error", ""))
    raw = llm.chat(prompt, system=prompts.SYSTEM)
    return {**state, "code": extract_code(raw), "attempts": state.get("attempts", 0) + 1}


def _node_validate(state: CodegenState) -> CodegenState:
    ok, output = run_checker_test(state["code"], state["test_code"])
    return {**state, "success": ok, "error": "" if ok else output}


def _node_save(state: CodegenState) -> CodegenState:
    out_dir = Path(settings.generated_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{state['rule_id']}.py").write_text(state["code"], encoding="utf-8")
    return state


def _route(state: CodegenState) -> str:
    if state.get("success"):
        return "save"
    if state.get("attempts", 0) >= settings.codegen_max_retries:
        return "give_up"
    return "generate"


def build_graph():
    from langgraph.graph import StateGraph, END

    g = StateGraph(CodegenState)
    g.add_node("generate", _node_generate)
    g.add_node("validate", _node_validate)
    g.add_node("save", _node_save)
    g.set_entry_point("generate")
    g.add_edge("generate", "validate")
    g.add_conditional_edges("validate", _route,
                            {"generate": "generate", "save": "save", "give_up": END})
    g.add_edge("save", END)
    return g.compile()


def generate_checker(rule_id: str, rule_text: str, test_code: str) -> CodegenState:
    """跑完整流水线，返回最终状态（含 success / code / error）。"""
    graph = build_graph()
    return graph.invoke({"rule_id": rule_id, "rule_text": rule_text,
                         "test_code": test_code, "attempts": 0})
