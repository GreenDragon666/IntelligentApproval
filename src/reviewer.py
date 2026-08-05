"""可选的本地 LLM 结果复核；不作为默认确定性执行的必需环节。"""

from __future__ import annotations

import json
import re

from config import settings
from . import llm
from .schema import MatchedRule, ReviewResult, RuleResult

_JSON_BLOCK = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def _evidence_for_review(rule: MatchedRule) -> list[dict]:
    remaining = settings.review_max_evidence_chars
    items: list[dict] = []
    for index, evidence in enumerate(rule.evidence):
        if remaining <= 0:
            break
        text = evidence.text[:remaining]
        remaining -= len(text)
        items.append(
            {
                "evidence_index": index,
                "location": {
                    "file": evidence.location.file,
                    "section": evidence.location.section,
                    "pdf_pages": {
                        "start": evidence.location.pdf_pages.start,
                        "end": evidence.location.pdf_pages.end,
                    },
                },
                "text": text,
            }
        )
    return items


def review(rule: MatchedRule, result: RuleResult) -> ReviewResult:
    payload = {
        "rule_id": rule.rule_id,
        "rule_raw": rule.rule_raw,
        "rule_text": rule.rule_text,
        "evidence": _evidence_for_review(rule),
        "checker_result": result.to_dict(),
    }
    prompt = f'''\
请复核下面的确定性 checker 结果是否严格符合规则和原文。
只返回 JSON：{{"approved": true或false, "feedback": "若不通过，说明代码应如何修正"}}。
不得添加 Markdown 或其他字段。

输入：
{json.dumps(payload, ensure_ascii=False)}
'''
    raw = llm.chat(
        prompt,
        system="你是招标文件合规校验结果复核员，只做一致性复核。",
        temperature=0.0,
        max_tokens=1024,
    )
    match = _JSON_BLOCK.search(raw)
    data = json.loads((match.group(1) if match else raw).strip())
    if type(data.get("approved")) is not bool:
        raise ValueError("LLM 复核结果缺少布尔字段 approved")
    return ReviewResult(
        approved=data["approved"], feedback=str(data.get("feedback", "")).strip()
    )
