"""为确定性结果补充可读的本地 LLM 分析，不改变执行器给出的状态。"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace

from config import settings
from .. import llm
from ..rule_parts import legal_basis, rule_description
from ..rule_schema import MatchedRule, RuleResult
from .json_output import extract_json_object

SYSTEM_PROMPT = """你是招标文件合规结果解释员。你要检查一个已经由确定性程序算出的结果是否与规则和证据相符，并给执法人员写出简洁、可解释的分析。
依据优先级：rule_raw 决定审查主题；legal_basis_reference 可补充明确的法律要求、数值和期限；description_reference 只帮助理解适用场景，不得单独新增阈值、条件或缺失输入。
不得修改 result.status，不得虚构证据，不得把规则中生成的公式或预设字段当成事实。只返回 JSON，不得输出 Markdown 或思考过程：
{"consistent":true,"analysis":"2至4句话，说明关键证据、计算结果为何支持或不足以支持当前状态，并指出判断边界","confidence":0到1}。"""


@dataclass(frozen=True)
class ResultExplanation:
    result: RuleResult
    attempts: int = 1
    raw: str = ""


class ExplanationError(RuntimeError):
    def __init__(self, message: str, *, attempts: int, raw: str = ""):
        super().__init__(message)
        self.attempts = attempts
        self.raw = raw


def _evidence(rule: MatchedRule) -> list[dict]:
    remaining = settings.review_max_evidence_chars
    items: list[dict] = []
    for index, evidence in enumerate(rule.evidence):
        if remaining <= 0:
            break
        text = evidence.text[: min(len(evidence.text), remaining, settings.semantic_max_chars_per_evidence)]
        remaining -= len(text)
        items.append({
            "evidence_index": index,
            "location": {
                "file": evidence.location.file,
                "section": evidence.location.section,
                "pdf_pages": [evidence.location.pdf_pages.start, evidence.location.pdf_pages.end],
                "page_basis": evidence.location.page_basis,
            },
            "text": text,
        })
    return items


def _parse(raw: str) -> dict:
    data = extract_json_object(raw, label="LLM 分析结果")
    if type(data.get("consistent")) is not bool:
        raise ValueError("LLM 分析结果缺少布尔字段 consistent")
    analysis = str(data.get("analysis", "")).strip()
    if not analysis:
        raise ValueError("LLM 分析结果缺少 analysis")
    confidence = float(data.get("confidence", 0.0))
    if not 0 <= confidence <= 1:
        raise ValueError("LLM 分析 confidence 必须在 0 到 1 之间")
    return {"consistent": data["consistent"], "analysis": analysis, "confidence": confidence}


def explain_result(rule: MatchedRule, result: RuleResult) -> ResultExplanation:
    """解释当前结果；模型只给意见，程序保留原 status、summary 和 findings。"""
    payload = {
        "rule_id": rule.rule_id,
        "check_method": rule.check_method,
        "rule_raw": rule.rule_raw,
        "description_reference": rule_description(rule.rule_text),
        "legal_basis_reference": legal_basis(rule.rule_text),
        "evidence": _evidence(rule),
        "result": result.to_dict(),
    }
    serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    last_error = ""
    last_raw = ""
    for attempt in range(1, settings.semantic_max_retries + 2):
        correction = f"\n上一次输出校验失败：{last_error}\n请只修正 JSON。" if last_error else ""
        try:
            last_raw = llm.chat(
                f"/no_think\n请分析以下规则校验结果。{correction}\n输入：{serialized}",
                system=SYSTEM_PROMPT,
                temperature=0.0,
                max_tokens=settings.semantic_max_tokens,
            )
            data = _parse(last_raw)
            break
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
    else:
        raise ExplanationError(f"LLM 结果分析连续失败 {settings.semantic_max_retries + 1} 次：{last_error}", attempts=settings.semantic_max_retries + 1, raw=last_raw[:2000])
    metrics = {
        **result.metrics,
        "llm_analysis_consistent": data["consistent"],
        "llm_analysis_confidence": data["confidence"],
    }
    return ResultExplanation(replace(result, analysis=data["analysis"], metrics=metrics), attempts=attempt)
