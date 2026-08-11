"""全局确定性规则执行器：从规则公式和证据文本提取可复用的检查操作。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from ..rule_schema import Finding, MatchedRule, RuleResult, Status

_DATE = re.compile(r"(?P<year>20\d{2})\s*[年./-]\s*(?P<month>\d{1,2})\s*[月./-]\s*(?P<day>\d{1,2})\s*日?(?:\s*(?P<hour>\d{1,2})\s*[时:]\s*(?P<minute>\d{1,2})?\s*分?)?")
_MONEY = re.compile(r"(?P<value>\d[\d,]*(?:\.\d+)?)\s*(?P<unit>亿元|万元|万|元)")
_PERCENT = re.compile(r"(?P<value>\d+(?:\.\d+)?)\s*%")
_FORMULA = re.compile(r"【公式】(?P<body>.*?)(?=\n\s*【|\Z)", re.DOTALL)
_LEGAL = re.compile(r"【法规依据】(?P<body>.*?)(?=\n\s*【|\Z)", re.DOTALL)
_MATCH = re.compile(r"MATCH\s*['\"](?P<terms>[^'\"]+)['\"]", re.IGNORECASE)
_RATIO = re.compile(r"(?P<numerator>[\u4e00-\u9fffA-Za-z0-9_.（）()]+金额)\s*/\s*(?P<denominator>[\u4e00-\u9fffA-Za-z0-9_.（）()]+(?:金额|估算价|预算))\s*(?P<operator>>=|<=|>|<)\s*(?P<threshold>0?\.\d+)")
_ABSOLUTE_MONEY = re.compile(r"(?P<field>[\u4e00-\u9fffA-Za-z0-9_.（）()]+金额)\s*(?P<operator>>=|<=|>|<)\s*(?P<threshold>\d{4,})")
_SCALAR_PERCENT = re.compile(r"(?P<field>[\u4e00-\u9fffA-Za-z0-9_.（）()]+比例)\s*(?P<operator>>=|<=|>|<)\s*(?P<threshold>0?\.\d+)")


@dataclass(frozen=True)
class ExtractedValue:
    value: float | datetime | str
    evidence_index: int
    quote: str


def _section(pattern: re.Pattern[str], text: str) -> str:
    match = pattern.search(text)
    return match.group("body").strip() if match else ""


def _legal_basis(rule: MatchedRule) -> str:
    return _section(_LEGAL, rule.rule_text)[:1600]


def _formula(rule: MatchedRule) -> str:
    return _section(_FORMULA, rule.rule_text) or rule.rule_text


def _field_names(rule: MatchedRule) -> list[str]:
    fields = []
    for value in re.split(r"[、,，;；]+", rule.structured_fields):
        value = value.strip()
        if value and value not in fields and not value.isdigit():
            fields.append(value)
    return fields


def _core_field(field: str) -> str:
    value = re.sub(r"字段|数据|数据库|列表|表$", "", field)
    value = value.replace("资审", "资格预审").replace("项目估算价", "合同估算价")
    return value.strip(" .。()（）")


def _field_tokens(field: str) -> list[str]:
    value = _core_field(field)
    stop = ("招标文件", "资格预审文件", "项目", "当前", "对应", "相关")
    for word in stop:
        value = value.replace(word, "")
    tokens = re.findall(r"[\u4e00-\u9fff]{2,}", value)
    expanded: list[str] = []
    for token in tokens:
        expanded.append(token)
        for marker in ("开始", "结束", "截止", "发布", "发出", "金额", "估算价", "预算", "日期", "时间"):
            if marker in token:
                remainder = token.replace(marker, "")
                if len(remainder) >= 2:
                    expanded.append(remainder)
                expanded.append(marker)
    if "发售" in value:
        expanded.extend(["获取", "获取时间"])
    if "估算价" in value:
        expanded.extend(["合同估算价", "项目估算价"])
    return list(dict.fromkeys(expanded))


def _formula_field(value: str) -> str:
    value = re.sub(r"^IF\s+", "", value.strip(), flags=re.IGNORECASE)
    return value.split(".")[-1].strip(" ()（）")


def _candidate_lines(rule: MatchedRule, field: str) -> list[tuple[int, str, int]]:
    tokens = _field_tokens(field)
    candidates: list[tuple[int, str, int]] = []
    for index, evidence in enumerate(rule.evidence):
        for line in evidence.text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            score = sum(1 for token in tokens if token in stripped)
            if score:
                candidates.append((index, stripped, score))
    return sorted(candidates, key=lambda item: (-item[2], item[0]))


def _money_value(field: str, rule: MatchedRule) -> ExtractedValue | None:
    for index, line, _score in _candidate_lines(rule, field):
        matches = list(_MONEY.finditer(line))
        if not matches:
            continue
        anchors = [line.find(token) for token in sorted(_field_tokens(field), key=len, reverse=True) if token in line]
        anchor = max(anchors, default=-1)
        match = next((candidate for candidate in matches if candidate.start() >= anchor), matches[0])
        number = float(match.group("value").replace(",", ""))
        multiplier = {"元": 1.0, "万": 10000.0, "万元": 10000.0, "亿元": 100000000.0}[match.group("unit")]
        return ExtractedValue(number * multiplier, index, match.group(0))
    return None


def _percent_value(field: str, rule: MatchedRule) -> ExtractedValue | None:
    for index, line, _score in _candidate_lines(rule, field):
        matches = list(_PERCENT.finditer(line))
        if matches:
            anchors = [line.find(token) for token in sorted(_field_tokens(field), key=len, reverse=True) if token in line]
            anchor = max(anchors, default=-1)
            match = next((candidate for candidate in matches if candidate.start() >= anchor), matches[0])
            return ExtractedValue(float(match.group("value")) / 100.0, index, match.group(0))
    return None


def _date_value(field: str, rule: MatchedRule) -> ExtractedValue | None:
    prefer_last = any(marker in field for marker in ("结束", "截止", "顺延后"))
    for index, line, _score in _candidate_lines(rule, field):
        matches = list(_DATE.finditer(line))
        if not matches:
            continue
        match = matches[-1] if prefer_last else matches[0]
        value = datetime(int(match.group("year")), int(match.group("month")), int(match.group("day")), int(match.group("hour") or 0), int(match.group("minute") or 0))
        return ExtractedValue(value, index, match.group(0))
    return None


def _finding(value: ExtractedValue, reason: str) -> Finding:
    return Finding(evidence_index=value.evidence_index, quote=value.quote, reason=reason)


def _trigger_status(formula: str, start: int, end: int) -> Status:
    line_start = formula.rfind("\n", 0, start) + 1
    line_end = formula.find("\n", end)
    line = formula[line_start:line_end if line_end >= 0 else len(formula)]
    return Status.WARNING if "预警" in line and "违规" not in line else Status.VIOLATION


def _status_result(rule: MatchedRule, status: Status, summary: str, *, findings: list[Finding] | None = None, metrics: dict | None = None, missing: list[str] | None = None) -> RuleResult:
    return RuleResult(rule_id=rule.rule_id, status=status, summary=summary, legal_basis=_legal_basis(rule), findings=findings or [], metrics=metrics or {}, confidence=1.0, missing_inputs=missing or [])


def _evaluate_keywords(rule: MatchedRule, formula: str) -> RuleResult | None:
    checks = []
    for match in _MATCH.finditer(formula):
        suffix = formula[match.end():match.end() + 120]
        status = Status.WARNING if "预警" in suffix and "违规" not in suffix.splitlines()[0] else Status.VIOLATION
        terms = [term.strip() for term in match.group("terms").split("|") if term.strip() and not any(char in term for char in "()（）<>=")]
        checks.append((terms, status))
    if not checks:
        return None
    for terms, status in checks:
        for evidence_index, evidence in enumerate(rule.evidence):
            for term in terms:
                found = evidence.text.find(term)
                if found >= 0:
                    finding = Finding(evidence_index=evidence_index, quote=term, reason=f"命中规则公式中的结构化关键词：{term}")
                    return _status_result(rule, status, "命中规则公式中声明的异常值。", findings=[finding], metrics={"matched_term": term})
    if re.search(r"\bNULL\b|<>|\s/\s|\s-\s", formula, re.IGNORECASE):
        return _status_result(rule, Status.INSUFFICIENT_INPUT, "关键词子条件未命中，但复合规则仍缺少其他结构化操作数。", missing=_field_names(rule))
    return _status_result(rule, Status.PASS, "未命中规则公式中声明的异常值。", metrics={"keyword_checks": sum(len(items) for items, _ in checks)})


def _evaluate_ratios(rule: MatchedRule, formula: str) -> RuleResult | None:
    checks = list(_RATIO.finditer(formula))
    if not checks:
        return None
    missing: list[str] = []
    evaluated = 0
    for match in checks:
        numerator_name = _formula_field(match.group("numerator"))
        denominator_name = _formula_field(match.group("denominator"))
        numerator = _money_value(numerator_name, rule)
        denominator = _money_value(denominator_name, rule)
        if numerator is None:
            missing.append(numerator_name)
        if denominator is None:
            missing.append(denominator_name)
        if numerator is None or denominator is None or float(denominator.value) == 0:
            continue
        evaluated += 1
        ratio = float(numerator.value) / float(denominator.value)
        threshold = float(match.group("threshold"))
        operator = match.group("operator")
        violated = {">": ratio > threshold, ">=": ratio >= threshold, "<": ratio < threshold, "<=": ratio <= threshold}[operator]
        if violated:
            status = _trigger_status(formula, match.start(), match.end())
            return _status_result(rule, status, f"结构化比例检查触发：{ratio:.2%} {operator} {threshold:.2%}。", findings=[_finding(numerator, f"{numerator_name}/{denominator_name}={ratio:.2%}")], metrics={"ratio": round(ratio, 6), "threshold": threshold})
    if evaluated:
        return _status_result(rule, Status.PASS, "结构化比例检查通过。", metrics={"evaluated_checks": evaluated})
    return _status_result(rule, Status.INSUFFICIENT_INPUT, "缺少执行结构化比例检查所需的数据。", missing=list(dict.fromkeys(missing)))


def _evaluate_absolute_money(rule: MatchedRule, formula: str) -> RuleResult | None:
    checks = list(_ABSOLUTE_MONEY.finditer(formula))
    if not checks:
        return None
    missing = []
    evaluated = 0
    for match in checks:
        field = _formula_field(match.group("field"))
        extracted = _money_value(field, rule)
        if extracted is None:
            missing.append(field)
            continue
        evaluated += 1
        current = float(extracted.value)
        threshold = float(match.group("threshold"))
        operator = match.group("operator")
        violated = {">": current > threshold, ">=": current >= threshold, "<": current < threshold, "<=": current <= threshold}[operator]
        if violated:
            status = _trigger_status(formula, match.start(), match.end())
            return _status_result(rule, status, f"结构化金额检查触发：{current:g} {operator} {threshold:g}。", findings=[_finding(extracted, f"{field}触发规则阈值")], metrics={"value": current, "threshold": threshold})
    if evaluated:
        return _status_result(rule, Status.PASS, "结构化金额检查通过。", metrics={"evaluated_checks": evaluated})
    return _status_result(rule, Status.INSUFFICIENT_INPUT, "缺少执行结构化金额检查所需的数据。", missing=list(dict.fromkeys(missing)))


def _evaluate_percentages(rule: MatchedRule, formula: str) -> RuleResult | None:
    checks = list(_SCALAR_PERCENT.finditer(formula))
    if not checks:
        return None
    missing = []
    evaluated = 0
    for match in checks:
        field = _formula_field(match.group("field"))
        extracted = _percent_value(field, rule)
        if extracted is None:
            missing.append(field)
            continue
        evaluated += 1
        current = float(extracted.value)
        threshold = float(match.group("threshold"))
        operator = match.group("operator")
        triggered = {">": current > threshold, ">=": current >= threshold, "<": current < threshold, "<=": current <= threshold}[operator]
        if triggered:
            status = _trigger_status(formula, match.start(), match.end())
            return _status_result(rule, status, f"结构化比例字段检查触发：{current:.2%} {operator} {threshold:.2%}。", findings=[_finding(extracted, f"{field}触发规则阈值")], metrics={"value": current, "threshold": threshold})
    if evaluated:
        return _status_result(rule, Status.PASS, "结构化比例字段检查通过。", metrics={"evaluated_checks": evaluated})
    return _status_result(rule, Status.INSUFFICIENT_INPUT, "缺少执行结构化比例字段检查所需的数据。", missing=list(dict.fromkeys(missing)))


def _evaluate_dates(rule: MatchedRule, formula: str) -> RuleResult | None:
    date_fields = [field for field in _field_names(rule) if "日期" in field or "时间" in field]
    if len(date_fields) < 2:
        return None
    threshold_match = re.search(r"<\s*(\d+)\s*(?:日|天|个工作日)?", formula)
    if threshold_match is None:
        threshold_match = re.search(r"(?:不少于|至少|≥)\s*(\d+)\s*(?:日|天|个工作日)?", formula)
    if not threshold_match:
        return None
    first = _date_value(date_fields[0], rule)
    second = _date_value(date_fields[1], rule)
    missing = [field for field, value in zip(date_fields[:2], (first, second)) if value is None]
    if first is None or second is None:
        return _status_result(rule, Status.INSUFFICIENT_INPUT, "缺少执行日期区间检查所需的数据。", missing=missing)
    if re.search(r"截止日期\s*<=\s*[^\n]*结束日期", formula) and second.value <= first.value:
        return _status_result(rule, Status.VIOLATION, "截止日期未晚于发售结束日期。", findings=[_finding(second, "截止日期必须晚于发售结束日期")])
    days = abs((second.value - first.value).days)
    if "开始" in date_fields[0] and "结束" in date_fields[1]:
        days += 1
    threshold = int(threshold_match.group(1))
    if days < threshold:
        status = _trigger_status(formula, threshold_match.start(), threshold_match.end())
        return _status_result(rule, status, f"日期间隔为 {days} 天，低于规则要求的 {threshold} 天。", findings=[_finding(second, f"日期间隔不足 {threshold} 天")], metrics={"days": days, "threshold_days": threshold})
    return _status_result(rule, Status.PASS, f"日期间隔为 {days} 天，满足不少于 {threshold} 天的要求。", metrics={"days": days, "threshold_days": threshold})


def evaluate_structured(rule: MatchedRule) -> RuleResult:
    """解释规则表中的公式；无法可靠取得操作数时返回输入不足，不猜测结论。"""
    if not rule.evidence:
        return _status_result(rule, Status.INSUFFICIENT_INPUT, "未匹配到可供结构化检查的原文。", missing=_field_names(rule))
    formula = _formula(rule)
    results = []
    for evaluator in (_evaluate_ratios, _evaluate_absolute_money, _evaluate_percentages, _evaluate_dates, _evaluate_keywords):
        result = evaluator(rule, formula)
        if result is not None:
            results.append(result)
    for status in (Status.VIOLATION, Status.WARNING):
        for result in results:
            if result.status == status:
                return result
    insufficient = [result for result in results if result.status == Status.INSUFFICIENT_INPUT]
    if insufficient:
        missing = list(dict.fromkeys(value for result in insufficient for value in result.missing_inputs))
        return _status_result(rule, Status.INSUFFICIENT_INPUT, "复合结构化规则缺少部分必要字段，不能给出完整结论。", missing=missing)
    if results and all(result.status == Status.PASS for result in results):
        return _status_result(rule, Status.PASS, "所有可解析的结构化子条件均检查通过。", metrics={"evaluated_subchecks": len(results)})
    fields = _field_names(rule)
    return _status_result(rule, Status.INSUFFICIENT_INPUT, "当前全局结构化执行器无法从证据中可靠取得规则所需字段。", metrics={"executor": "structured", "formula_detected": bool(formula)}, missing=fields)
