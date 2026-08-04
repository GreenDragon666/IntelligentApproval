"""Checker 注册表：运行时按 rule_id 查找并执行 checker。

每个 checker 是签名固定的纯函数 `check(ctx: TenderContext) -> RuleResult`。
LangGraph 代码生成流水线产出的 checker 落库后，用 @register 注册到这里。
"""

from __future__ import annotations

from typing import Callable

from .schema import TenderContext, RuleResult

Checker = Callable[[TenderContext], RuleResult]

_REGISTRY: dict[str, Checker] = {}


def register(rule_id: str) -> Callable[[Checker], Checker]:
    def deco(fn: Checker) -> Checker:
        if rule_id in _REGISTRY:
            raise ValueError(f"rule_id 重复注册: {rule_id}")
        _REGISTRY[rule_id] = fn
        return fn
    return deco


def get(rule_id: str) -> Checker:
    return _REGISTRY[rule_id]


def all_checkers() -> dict[str, Checker]:
    return dict(_REGISTRY)


def load_builtin() -> None:
    """导入内置 checker 模块，触发 @register 副作用。"""
    from . import checkers  # noqa: F401  (checkers/__init__ 汇总导入各 rule 模块)
