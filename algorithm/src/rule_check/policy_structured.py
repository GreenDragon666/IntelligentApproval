"""对高频、可明确形式化的政策规则执行确定性检查。

这些检查只在规则表明确选择“结构化数据检查”时由上层调用，
不依赖 LLM 生成的公式和字段名。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..rule_parts import legal_basis
from ..rule_schema import Finding, MatchedRule, RuleResult, Status

_SPACE = re.compile(r"\s+")
_NUMBER = r"[零○一二两三四五六七八九十\d]+"


@dataclass(frozen=True)
class _Hit:
    evidence_index: int
    quote: str
    value: float | None = None


def _compact_with_positions(text: str) -> tuple[str, list[int]]:
    chars: list[str] = []
    positions: list[int] = []
    for index, char in enumerate(text):
        if not char.isspace():
            chars.append(char)
            positions.append(index)
    return "".join(chars), positions


def _search(rule: MatchedRule, pattern: re.Pattern[str]) -> list[_Hit]:
    hits: list[_Hit] = []
    for evidence_index, evidence in enumerate(rule.evidence):
        compact, positions = _compact_with_positions(evidence.text)
        for match in pattern.finditer(compact):
            if not positions:
                continue
            start = positions[match.start()]
            end = positions[match.end() - 1] + 1
            value = float(match.group("value")) if "value" in pattern.groupindex and match.group("value") else None
            hits.append(_Hit(evidence_index, evidence.text[start:end], value))
    return hits


def _number(value: str) -> int | None:
    if value.isdigit():
        return int(value)
    value = value.replace("两", "二").replace("○", "零")
    digits = {"零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    if value == "十":
        return 10
    if "十" in value:
        left, right = value.split("十", 1)
        return digits.get(left, 1) * 10 + digits.get(right, 0)
    return digits.get(value)


def _result(rule: MatchedRule, status: Status, summary: str, *, hit: _Hit | None = None, reason: str = "", metrics: dict | None = None) -> RuleResult:
    findings = [Finding(hit.evidence_index, hit.quote, reason)] if hit is not None and status in {Status.VIOLATION, Status.WARNING} else []
    return RuleResult(
        rule_id=rule.rule_id,
        status=status,
        summary=summary,
        legal_basis=legal_basis(rule.rule_text)[:1600],
        findings=findings,
        metrics={"policy_checker": True, **(metrics or {})},
        confidence=1.0,
    )


def _performance_guarantee(rule: MatchedRule) -> RuleResult:
    rejection = re.compile(r"履约保证金.{0,100}(?:须|必须|只能|仅限|只接受).{0,30}(?:现金|电汇).{0,120}(?:不接受|拒收|不得采用).{0,60}(?:保函|保单|非现金)")
    hits = _search(rule, rejection)
    if hits:
        return _result(rule, Status.VIOLATION, "履约保证金被明确限定为现金形式。", hit=hits[0], reason="原文明确要求现金并排除保函、保单等非现金形式。")

    alternatives = re.compile(r"履约保证金.{0,100}(?:现金|转账|电汇).{0,30}(?:或|或者|以及).{0,50}(?:保函|保单|非现金)")
    if _search(rule, alternatives):
        return _result(rule, Status.PASS, "履约保证金提供了现金和非现金备选形式。")

    exclusive = re.compile(r"履约保证金.{0,100}(?:只能|仅限|只接受|必须以|须以).{0,20}(?:现金|电汇)")
    hits = _search(rule, exclusive)
    if hits:
        return _result(rule, Status.VIOLATION, "履约保证金被限定为现金形式。", hit=hits[0], reason="原文使用排他性表述限定现金或电汇形式。")
    return _result(rule, Status.WARNING, "当前证据未提取到可靠的履约保证金形式，需语义复核。", metrics={"requires_review": True})


def _publicity_period(rule: MatchedRule) -> RuleResult:
    pattern = re.compile(rf"(?:中标候选人)?公示期(?:限)?(?:：|:|为)?(?P<operator>不得少于|不少于|至少|不足|少于)?(?P<number>{_NUMBER})(?:个工作日|工作日|个自然日|自然日|日|天)")
    values: list[tuple[_Hit, int, str]] = []
    for evidence_index, evidence in enumerate(rule.evidence):
        compact, positions = _compact_with_positions(evidence.text)
        for match in pattern.finditer(compact):
            number = _number(match.group("number"))
            if number is None:
                continue
            start, end = positions[match.start()], positions[match.end() - 1] + 1
            values.append((_Hit(evidence_index, evidence.text[start:end], float(number)), number, match.group("operator") or ""))
    for hit, number, operator in values:
        if number < 3 and operator not in {"不足", "少于"}:
            return _result(rule, Status.VIOLATION, f"中标候选人公示期为 {number} 日，低于 3 日。", hit=hit, reason="公示期限的明确数值低于法定下限。", metrics={"days": number, "threshold_days": 3})
        if operator in {"不足", "少于"} and number <= 3:
            return _result(rule, Status.VIOLATION, "中标候选人公示期明确低于 3 日。", hit=hit, reason="原文明确规定公示期不足法定下限。", metrics={"threshold_days": 3})
    if values:
        days = [number for _hit, number, _operator in values]
        return _result(rule, Status.PASS, "已提取的中标候选人公示期不低于 3 日。", metrics={"days": days, "threshold_days": 3})
    return _result(rule, Status.WARNING, "当前证据未提取到中标候选人公示期数值，需语义复核。", metrics={"requires_review": True})


def _advance_payment(rule: MatchedRule) -> RuleResult:
    combined_text = "\n".join(evidence.text for evidence in rule.evidence)
    if "重大工程项目" in combined_text and re.search(r"按年度|逐年.{0,12}预付", combined_text):
        return _result(rule, Status.WARNING, "证据涉及重大工程按年度预付，不能直接套用一般比例区间，需人工复核。", metrics={"requires_review": True, "major_project_exception": True})

    none_pattern = re.compile(r"(?:本项目|本工程|施工项目)?.{0,20}(?:不支付|不设|无)(?:工程)?预付款|预付款.{0,20}?(?:为|：|:)?(?<!\d)0%")
    hits = _search(rule, none_pattern)
    if hits:
        return _result(rule, Status.VIOLATION, "施工项目预付款为 0%或明确不支付，低于 10%。", hit=hits[0], reason="不支付预付款等同于预付比例为 0%。", metrics={"percentage": 0.0, "minimum": 0.1, "maximum": 0.3})

    patterns = (
        re.compile(r"预付款.{0,60}?(?<!\d)(?P<value>\d+(?:\.\d+)?)%"),
        re.compile(r"(?<!\d)(?P<value>\d+(?:\.\d+)?)%.{0,20}?(?:的)?(?:工程)?预付款"),
    )
    hits: list[_Hit] = []
    for pattern in patterns:
        hits.extend(_search(rule, pattern))
    # 重叠表述只保留“证据+数值”组合的第一次出现。
    unique: list[_Hit] = []
    seen: set[tuple[int, float | None]] = set()
    for hit in hits:
        key = (hit.evidence_index, hit.value)
        if key not in seen:
            seen.add(key)
            unique.append(hit)
    for hit in unique:
        assert hit.value is not None
        ratio = hit.value / 100.0
        if ratio < 0.1 or ratio > 0.3:
            return _result(rule, Status.VIOLATION, f"施工项目预付款比例为 {hit.value:g}%，不在 10%～30% 范围内。", hit=hit, reason="预付款比例超出规则及法规依据明确的范围。", metrics={"percentage": ratio, "minimum": 0.1, "maximum": 0.3})
    if unique:
        ratios = [hit.value / 100.0 for hit in unique if hit.value is not None]
        return _result(rule, Status.PASS, "已提取的施工项目预付款比例位于 10%～30% 范围内。", metrics={"percentages": ratios, "minimum": 0.1, "maximum": 0.3})
    return _result(rule, Status.WARNING, "当前证据未提取到明确的施工预付款比例，需语义复核。", metrics={"requires_review": True})


def evaluate_known_policy_rule(rule: MatchedRule) -> RuleResult | None:
    """命中已验证的通用政策模板时返回结果，否则交回原通用执行器。"""
    compact = _SPACE.sub("", rule.rule_raw)
    if "履约保证金" in compact and "现金" in compact:
        return _performance_guarantee(rule)
    if "中标候选人公示期" in compact and "3日" in compact:
        return _publicity_period(rule)
    if "预付款" in compact and "10%" in compact:
        return _advance_payment(rule)
    return None
