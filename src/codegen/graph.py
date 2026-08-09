"""本地模型 checker 生成、契约验证、失败重试和落库。"""

from __future__ import annotations

from typing import Any, TypedDict

from config import settings
from .. import llm
from ..checker_store import CheckerStore, checker_key
from ..rule_schema import MatchedRule
from . import prompts
from .sandbox import extract_code, validate_checker


class CodegenState(TypedDict, total=False):
    rule: dict[str, Any]
    feedback: str
    code: str
    error: str
    attempts: int
    success: bool
    checker_key: str
    checker_path: str
    store_root: str


def _state_rule(state: CodegenState) -> MatchedRule:
    return MatchedRule.from_dict(state["rule"])


def _node_generate(state: CodegenState) -> CodegenState:
    rule = _state_rule(state)
    attempts = state.get("attempts", 0)
    if attempts == 0 and state.get("code"):
        prompt = prompts.build_retry_prompt(
            rule.rule_id,
            rule.rule_raw,
            rule.rule_text,
            state["code"],
            state.get("feedback", "要求重新生成 checker"),
            state.get("feedback", ""),
        )
    elif attempts == 0:
        prompt = prompts.build_generate_prompt(
            rule.rule_id, rule.rule_raw, rule.rule_text, state.get("feedback", "")
        )
    else:
        prompt = prompts.build_retry_prompt(
            rule.rule_id,
            rule.rule_raw,
            rule.rule_text,
            state.get("code", ""),
            state.get("error", ""),
            state.get("feedback", ""),
        )
    raw = llm.chat(prompt, system=prompts.SYSTEM)
    return {**state, "code": extract_code(raw), "attempts": attempts + 1}


def _node_validate(state: CodegenState) -> CodegenState:
    ok, error = validate_checker(state.get("code", ""), _state_rule(state))
    return {**state, "success": ok, "error": "" if ok else error}


def _node_save(state: CodegenState) -> CodegenState:
    rule = _state_rule(state)
    code_path, _ = CheckerStore(state.get("store_root") or None).save(
        rule, state["code"], attempts=state.get("attempts", 0)
    )
    return {
        **state,
        "checker_key": checker_key(rule),
        "checker_path": str(code_path),
    }


def _route(state: CodegenState) -> str:
    if state.get("success"):
        return "save"
    if state.get("attempts", 0) >= settings.codegen_max_retries:
        return "give_up"
    return "generate"


def build_graph():
    from langgraph.graph import END, StateGraph

    graph = StateGraph(CodegenState)
    graph.add_node("generate", _node_generate)
    graph.add_node("validate", _node_validate)
    graph.add_node("save", _node_save)
    graph.set_entry_point("generate")
    graph.add_edge("generate", "validate")
    graph.add_conditional_edges(
        "validate",
        _route,
        {"generate": "generate", "save": "save", "give_up": END},
    )
    graph.add_edge("save", END)
    return graph.compile()


def generate_checker(
    rule: MatchedRule,
    feedback: str = "",
    store_root: str | None = None,
    previous_code: str = "",
) -> CodegenState:
    return build_graph().invoke(
        {
            "rule": rule.to_dict(),
            "feedback": feedback,
            "code": previous_code,
            "attempts": 0,
            "store_root": store_root or "",
        }
    )
