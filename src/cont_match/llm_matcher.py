"""使用本地 Qwen 对字符级召回结果进行规则—章节重排。"""

from __future__ import annotations

import json
import re

from config import settings
from .. import llm
from ..page_schema import PolicyRule, SectionCandidate
from ..rule_parts import legal_basis

_JSON_BLOCK = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def _candidate_excerpt(rule: PolicyRule, text: str, max_chars: int) -> str:
    """从长章节中截取与 rule_raw 字符重叠最高的窗口，而非固定取开头。"""
    if len(text) <= max_chars:
        return text
    def terms(value: str) -> set[str]:
        compact = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", value.lower())
        return {compact[index:index + size] for size in (2, 3) for index in range(max(0, len(compact) - size + 1))}

    raw_terms = terms(rule.rule_raw)
    legal_terms = terms(legal_basis(rule.rule_text))
    if not raw_terms and not legal_terms:
        return text[:max_chars]
    stride = max(1, max_chars // 3)
    starts = list(range(0, max(1, len(text) - max_chars + 1), stride))
    last = max(0, len(text) - max_chars)
    if not starts or starts[-1] != last:
        starts.append(last)

    def score(start: int) -> tuple[int, int]:
        window = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", text[start:start + max_chars].lower())
        return 3 * sum(term in window for term in raw_terms) + sum(term in window for term in legal_terms), -start

    best_start = max(starts, key=score)
    return text[best_start:best_start + max_chars]


def _parse_json_object(raw: str) -> dict:
    """从 JSON 代码块或带思考文本的回答中提取第一个对象。"""
    fenced = _JSON_BLOCK.search(raw)
    if fenced:
        value = json.loads(fenced.group(1).strip())
        if isinstance(value, dict):
            return value
    decoder = json.JSONDecoder()
    for index, char in enumerate(raw):
        if char != "{":
            continue
        try:
            value, _end = decoder.raw_decode(raw[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise ValueError("LLM 输出中没有可解析的 JSON 对象")


def select_candidates(
    rule: PolicyRule,
    candidates: list[SectionCandidate],
    *,
    max_selected: int = 2,
) -> list[SectionCandidate]:
    """让本地 Qwen 从字符召回候选中选择相关章节，也允许全部拒绝。"""
    if not candidates:
        return []
    payload = {
        "rule_id": rule.rule_id,
        "rule_raw": rule.rule_raw,
        "legal_basis_reference": legal_basis(rule.rule_text),
        "check_method": rule.check_method,
        "candidates": [
            {
                "index": index,
                "title": candidate.section.title,
                "pdf_pages": [candidate.section.pdf_start, candidate.section.pdf_end],
                "text": _candidate_excerpt(rule, candidate.section.text, settings.llm_candidate_chars),
                "lexical_score": round(candidate.score, 6),
            }
            for index, candidate in enumerate(candidates)
        ],
    }
    prompt = f'''/no_think
你负责把“重点排查情形”匹配到最相关的招标文件章节。
rule_raw 决定审查主题，legal_basis_reference 是补充法规依据，可用于理解具体法律概念、数值和期限。不得使用未提供的公式、开发说明或字段要求，也不要因为只出现通用法律词汇就选择。
如果没有候选真正相关，selected_indices 返回空数组。
只输出 JSON：{{"selected_indices": [整数下标], "reason": "简短理由"}}。
最多选择 {max_selected} 个，禁止输出 Markdown。

输入：
{json.dumps(payload, ensure_ascii=False)}
'''
    raw = llm.chat(
        prompt,
        system="你是招标文件章节匹配专家，只基于给定规则和候选原文作答。",
        temperature=0.0,
        max_tokens=512,
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        api_key=settings.llm_api_key,
    )
    data = _parse_json_object(raw)
    indices = data.get("selected_indices")
    if not isinstance(indices, list):
        raise ValueError("LLM 匹配结果缺少 selected_indices 数组")
    selected: list[SectionCandidate] = []
    for value in indices:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("selected_indices 必须是整数数组")
        if value < 0 or value >= len(candidates):
            raise ValueError(f"候选下标越界: {value}")
        if candidates[value] not in selected:
            selected.append(candidates[value])
        if len(selected) >= max_selected:
            break
    return selected
