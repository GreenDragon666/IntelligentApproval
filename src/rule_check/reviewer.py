"""可选的第二次本地 LLM 结果复核；默认关闭以控制延迟。"""

from __future__ import annotations

import json
import re

from config import settings
from .. import llm
from ..rule_schema import MatchedRule, ReviewResult, RuleResult

_JSON_BLOCK = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def _evidence(rule: MatchedRule) -> list[dict]:
    remaining = settings.review_max_evidence_chars
    items = []
    for index, evidence in enumerate(rule.evidence):
        if remaining <= 0:
            break
        text = evidence.text[:remaining]
        remaining -= len(text)
        items.append({"evidence_index": index, "location": {"file": evidence.location.file, "section": evidence.location.section, "pdf_pages": [evidence.location.pdf_pages.start, evidence.location.pdf_pages.end], "page_basis": evidence.location.page_basis}, "text": text})
    return items


def review(rule: MatchedRule, result: RuleResult) -> ReviewResult:
    payload = {"rule_id": rule.rule_id, "check_method": rule.check_method, "rule_raw": rule.rule_raw, "rule_text": rule.rule_text, "evidence": _evidence(rule), "result": result.to_dict()}
    raw = llm.chat(f'/no_think\n复核下面的规则校验结果。只返回 JSON：{{"approved":true或false,"feedback":"原因"}}。\n输入：{json.dumps(payload, ensure_ascii=False)}', system="你是招标文件合规校验结果复核员，只检查结论是否与规则和原文一致。", temperature=0.0, max_tokens=512)
    match = _JSON_BLOCK.search(raw)
    data = json.loads((match.group(1) if match else raw).strip())
    if type(data.get("approved")) is not bool:
        raise ValueError("LLM 复核结果缺少布尔字段 approved")
    return ReviewResult(approved=data["approved"], feedback=str(data.get("feedback", "")).strip())
