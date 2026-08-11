"""规范化规则表中的“检查方式”，并决定第三步执行器。"""

from __future__ import annotations

import re

STRUCTURED_METHOD = "结构化数据检查"
SEMANTIC_METHOD = "大模型分析"


def normalize_check_method(value: str) -> str:
    """统一全角符号、空白和组合顺序，不丢失规则表原有方法名称。"""
    parts = [part.strip() for part in re.split(r"[+＋、,，/]+", str(value or "")) if part.strip()]
    if not parts:
        return SEMANTIC_METHOD
    unique: list[str] = []
    for part in parts:
        if part not in unique:
            unique.append(part)
    return "+".join(unique)


def is_structured_method(value: str) -> bool:
    """只要组合中包含结构化数据检查，就使用全局确定性执行器。"""
    return STRUCTURED_METHOD in normalize_check_method(value).split("+")


def executor_name(value: str) -> str:
    return "structured" if is_structured_method(value) else "semantic_llm"
