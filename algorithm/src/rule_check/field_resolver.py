"""用语义模型把预设字段映射到正则已发现的值位置，不让模型提取数值。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

from config import settings
from .. import llm
from ..rule_parts import legal_basis
from ..rule_schema import MatchedRule
from .json_output import extract_json_object


@dataclass(frozen=True)
class ValueCandidate:
    """正则提取出的值及其上下文；数值本身不发送给语义模型。"""

    kind: str
    value: float | datetime
    evidence_index: int
    quote: str
    context: str


def resolve_field_values(rule: MatchedRule, fields: list[str], candidates: list[ValueCandidate]) -> dict[str, ValueCandidate]:
    """让模型只选择“字段对应哪个正则候选”，返回值始终来自正则结果。"""
    unique_fields = list(dict.fromkeys(field.strip() for field in fields if field.strip()))
    if not unique_fields or not candidates:
        return {}
    payload = {
        "rule_raw": rule.rule_raw,
        "legal_basis_reference": legal_basis(rule.rule_text),
        "fields": unique_fields,
        "value_candidates": [
            {
                "candidate_index": index,
                "kind": candidate.kind,
                "evidence_index": candidate.evidence_index,
                "context": candidate.context,
            }
            for index, candidate in enumerate(candidates)
        ],
    }
    prompt = f'''/no_think
你只负责字段别名匹配，不提取、不读取、不计算数值。
value_candidates 已由正则找到，每个 <VALUE> 代表该候选的值位置。请判断预设 fields 与文本中的近义字段、别名或不同表述是否指向同一数据概念。
每个字段最多选择一个 candidate_index；不确定就填 null。不得因为数值大小猜测字段。
只输出 JSON：{{"mappings":[{{"field":"原字段名","candidate_index":整数或null,"confidence":0到1}}]}}，禁止 Markdown。

输入：
{json.dumps(payload, ensure_ascii=False, separators=(",", ":"))}
'''
    raw = llm.chat(prompt, system="你是字段别名映射器，只能在给定正则候选中选择位置。", temperature=0.0, max_tokens=512, base_url=settings.llm_base_url, model=settings.llm_model, api_key=settings.llm_api_key)
    data = extract_json_object(raw, label="字段语义映射输出")
    mappings = data.get("mappings")
    if not isinstance(mappings, list):
        raise ValueError("字段语义映射缺少 mappings 数组")
    resolved: dict[str, ValueCandidate] = {}
    used: set[int] = set()
    for item in mappings:
        if not isinstance(item, dict):
            continue
        field = str(item.get("field", "")).strip()
        index = item.get("candidate_index")
        confidence = float(item.get("confidence", 0.0))
        if field not in unique_fields or index is None or isinstance(index, bool) or not isinstance(index, int):
            continue
        if confidence < 0.6 or index < 0 or index >= len(candidates) or index in used:
            continue
        resolved[field] = candidates[index]
        used.add(index)
    return resolved
