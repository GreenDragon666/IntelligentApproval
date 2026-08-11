"""全局确定性规则执行器：从规则公式和证据文本提取可复用的检查操作。"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime

from ..rule_parts import legal_basis
from ..rule_schema import Finding, MatchedRule, RuleResult, Status
from .field_resolver import ValueCandidate, resolve_field_values

_DATE = re.compile(r"(?P<year>20\d{2})\s*[年./-]\s*(?P<month>\d{1,2})\s*[月./-]\s*(?P<day>\d{1,2})\s*日?(?:\s*(?P<hour>\d{1,2})\s*[时:]\s*(?P<minute>\d{1,2})?\s*分?)?")
_MONEY = re.compile(r"(?P<value>\d[\d,]*(?:\.\d+)?)\s*(?P<unit>亿元|万元|万|元)")
_PERCENT = re.compile(r"(?P<value>\d+(?:\.\d+)?)\s*%")
_RATIO = re.compile(r"(?P<numerator>[\u4e00-\u9fffA-Za-z0-9_.（）()]+金额)\s*/\s*(?P<denominator>[\u4e00-\u9fffA-Za-z0-9_.（）()]+(?:金额|估算价|预算|总额|总价))\s*(?P<operator>>=|<=|>|<)\s*(?P<threshold>0?\.\d+)")
_ABSOLUTE_MONEY = re.compile(r"(?P<field>[\u4e00-\u9fffA-Za-z0-9_.（）()]+金额)\s*(?P<operator>>=|<=|>|<)\s*(?P<threshold>\d{4,})")
_SCALAR_PERCENT = re.compile(r"(?P<field>[\u4e00-\u9fffA-Za-z0-9_.（）()]+比例)\s*(?P<operator>>=|<=|>|<)\s*(?P<threshold>0?\.\d+)")


@dataclass(frozen=True)
class ExtractedValue:
    value: float | datetime | str
    evidence_index: int
    quote: str


def _legal_basis(rule: MatchedRule) -> str:
    return legal_basis(rule.rule_text)[:1600]


def _criterion_text(rule: MatchedRule) -> str:
    return "\n".join(value for value in (rule.rule_raw, legal_basis(rule.rule_text)) if value)


def _trigger_operator(text: str) -> str | None:
    if any(marker in text for marker in ("不得超过", "不超过", "不得高于", "最高不得超过", "超过", "高于", "大于", "上限")):
        return ">"
    if any(marker in text for marker in ("不得低于", "不低于", "不得少于", "不少于", "至少", "低于", "小于", "少于", "下限")):
        return "<"
    return None


def _decimal_number(value: str) -> int | None:
    if value.isdigit():
        return int(value)
    digits = {"零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    if value == "十":
        return 10
    if "十" in value:
        left, right = value.split("十", 1)
        return digits.get(left, 1) * 10 + digits.get(right, 0)
    return digits.get(value)


def _field_from_clause(text: str, *, fallback: str = "") -> str:
    value = re.split(r"[：:，,；;。]", text)[-1]
    known = re.findall(r"投标保证金|履约保证金|工程质量保证金|质量保证金|保证金总预留比例|合同预付款比例|预付款比例|价格分值|质保期|缺陷责任期", value)
    field = known[-1] if known else value[-18:]
    field = re.sub(r"^(?:要求|提交|预留|一般)", "", field).strip(" 的")
    return field or fallback


def _derived_plan(rule: MatchedRule) -> str:
    """只从 rule_raw 与【法规依据】推导通用操作，不读取【公式】或开发说明。"""
    criterion = _criterion_text(rule).replace("％", "%")
    clauses = [value.strip() for value in re.split(r"[。；;，,\n]+", criterion) if value.strip()]
    checks: list[str] = []
    numeric_topic = any(marker in rule.rule_raw for marker in ("金额", "比例", "%", "％", "预算", "估算价", "价款", "合规"))
    denominator_pattern = re.compile(r"(?P<field>招标项目估算价|项目估算价|采购项目预算金额|预算金额|中标合同金额|合同金额|工程价款结算总额|投标总价|金额总额|总金额)\s*的?\s*(?P<percent>\d+(?:\.\d+)?)%")
    percent_pattern = re.compile(r"(?P<percent>\d+(?:\.\d+)?)%")
    money_pattern = re.compile(r"(?P<value>\d[\d,]*(?:\.\d+)?)\s*(?P<unit>亿元|万元|万|元)")

    for clause in clauses:
        operator = _trigger_operator(clause)
        if operator is None or not numeric_topic:
            continue
        denominator_match = denominator_pattern.search(clause)
        if denominator_match:
            relation_at = min((position for marker in ("不得超过", "不超过", "不得高于", "超过", "高于", "大于", "不得低于", "不低于", "不少于", "至少", "低于", "小于", "少于") if (position := clause.find(marker)) >= 0), default=-1)
            left = clause[:relation_at] if relation_at >= 0 else clause[:denominator_match.start()]
            numerator = _field_from_clause(left, fallback="待检查金额")
            if not numerator.endswith("金额"):
                numerator = re.sub(r"比例$", "", numerator) + "金额"
            denominator = denominator_match.group("field")
            threshold = float(denominator_match.group("percent")) / 100.0
            checks.append(f"{numerator}/{denominator} {operator} {threshold:g}")
            continue

        percent_match = percent_pattern.search(clause)
        if percent_match:
            relation_positions = [clause.find(marker) for marker in ("不得超过", "不超过", "不得高于", "超过", "高于", "大于", "不得低于", "不低于", "不少于", "至少", "低于", "小于", "少于") if clause.find(marker) >= 0]
            before = clause[:min(relation_positions)] if relation_positions else clause[:percent_match.start()]
            field = _field_from_clause(before, fallback="待检查比例")
            if not field.endswith("比例"):
                field += "比例"
            threshold = float(percent_match.group("percent")) / 100.0
            checks.append(f"{field} {operator} {threshold:g}")

        money_match = money_pattern.search(clause)
        if money_match:
            relation_positions = [clause.find(marker) for marker in ("不得超过", "不超过", "不得高于", "超过", "高于", "大于", "不得低于", "不低于", "不少于", "至少", "低于", "小于", "少于") if clause.find(marker) >= 0]
            before = clause[:min(relation_positions)] if relation_positions else clause[:money_match.start()]
            field = _field_from_clause(before, fallback="待检查金额")
            if not field.endswith("金额"):
                field += "金额"
            number = float(money_match.group("value").replace(",", ""))
            multiplier = {"元": 1, "万": 10000, "万元": 10000, "亿元": 100000000}[money_match.group("unit")]
            checks.append(f"{field} {operator} {number * multiplier:g}")

    date_fields = [field for field in _field_names(rule) if "日期" in field or "时间" in field]
    if len(date_fields) >= 2:
        for clause in clauses:
            if not any(marker in clause for marker in ("发售期", "提供期限", "获取时间", "截止", "最短", "公示期", "日前")):
                continue
            match = re.search(r"(?:不得少于|不少于|至少|最短不得少于)\s*([零一二三四五六七八九十\d]+)\s*(?:个工作日|工作日|日|天)", clause)
            if match:
                threshold = _decimal_number(match.group(1))
                if threshold is not None:
                    checks.append(f"({date_fields[1]} - {date_fields[0]}) < {threshold}")
                    break
    return "\n".join(dict.fromkeys(checks))


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


def _resolved_value(field: str, kind: str, resolved: dict[str, ValueCandidate] | None) -> ExtractedValue | None:
    candidate = (resolved or {}).get(field)
    if candidate is None or candidate.kind != kind:
        return None
    return ExtractedValue(candidate.value, candidate.evidence_index, candidate.quote)


def _money_value(field: str, rule: MatchedRule, resolved: dict[str, ValueCandidate] | None = None) -> ExtractedValue | None:
    if resolved is not None:
        return _resolved_value(field, "money", resolved)
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


def _percent_value(field: str, rule: MatchedRule, resolved: dict[str, ValueCandidate] | None = None) -> ExtractedValue | None:
    if resolved is not None:
        return _resolved_value(field, "percent", resolved)
    for index, line, _score in _candidate_lines(rule, field):
        matches = list(_PERCENT.finditer(line))
        if matches:
            anchors = [line.find(token) for token in sorted(_field_tokens(field), key=len, reverse=True) if token in line]
            anchor = max(anchors, default=-1)
            match = next((candidate for candidate in matches if candidate.start() >= anchor), matches[0])
            return ExtractedValue(float(match.group("value")) / 100.0, index, match.group(0))
    return None


def _date_value(field: str, rule: MatchedRule, resolved: dict[str, ValueCandidate] | None = None) -> ExtractedValue | None:
    if resolved is not None:
        return _resolved_value(field, "date", resolved)
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


def _ratio_threshold_is_authoritative(rule: MatchedRule, threshold: float) -> bool:
    percent = threshold * 100
    forms = {f"{percent:g}%", f"{percent:g}％"}
    return any(value in _criterion_text(rule).replace(" ", "") for value in forms)


def _operator_is_authoritative(rule: MatchedRule, operator: str) -> bool:
    """确认派生操作的触发方向与 rule_raw/法规依据的上限、下限表述一致。"""
    compact = _criterion_text(rule).replace(" ", "")
    upper = any(marker in compact for marker in ("不得超过", "不超过", "超过", "大于", "高于", "上限"))
    lower = any(marker in compact for marker in ("不得低于", "不低于", "不少于", "至少", "低于", "小于", "少于", "下限"))
    return (upper and operator in {">", ">="}) or (lower and operator in {"<", "<="})


def _money_threshold_is_authoritative(rule: MatchedRule, threshold: float) -> bool:
    compact = _criterion_text(rule).replace(",", "").replace(" ", "")
    forms = {f"{threshold:g}元", f"{threshold:g}"}
    if threshold % 10000 == 0:
        forms.update({f"{threshold / 10000:g}万元", f"{threshold / 10000:g}万"})
    if threshold % 100000000 == 0:
        forms.add(f"{threshold / 100000000:g}亿元")
    return any(value in compact for value in forms)


def _date_threshold_is_authoritative(rule: MatchedRule, threshold: int) -> bool:
    for match in re.finditer(r"([零一二三四五六七八九十\d]+)\s*(?:个工作日|工作日|日|天)", _criterion_text(rule)):
        if _decimal_number(match.group(1)) == threshold:
            return True
    return False


def _evaluate_ratios(rule: MatchedRule, formula: str, resolved: dict[str, ValueCandidate] | None = None) -> RuleResult | None:
    checks = list(_RATIO.finditer(formula))
    if not checks:
        return None
    missing: list[str] = []
    evaluated = 0
    for match in checks:
        numerator_name = _formula_field(match.group("numerator"))
        denominator_name = _formula_field(match.group("denominator"))
        threshold = float(match.group("threshold"))
        operator = match.group("operator")
        if not _ratio_threshold_is_authoritative(rule, threshold) or not _operator_is_authoritative(rule, operator):
            return _status_result(rule, Status.WARNING, "派生的比例阈值或比较方向未能从重点排查情形/法规依据中复核，已停止自动判定。", metrics={"requires_review": True, "criterion_source": "unverified"})
        numerator = _money_value(numerator_name, rule, resolved)
        denominator = _money_value(denominator_name, rule, resolved)
        if numerator is None:
            missing.append(numerator_name)
        if denominator is None:
            missing.append(denominator_name)
        if numerator is None or denominator is None or float(denominator.value) == 0:
            continue
        evaluated += 1
        ratio = float(numerator.value) / float(denominator.value)
        violated = {">": ratio > threshold, ">=": ratio >= threshold, "<": ratio < threshold, "<=": ratio <= threshold}[operator]
        if violated:
            status = _trigger_status(formula, match.start(), match.end())
            return _status_result(rule, status, f"结构化比例检查触发：{ratio:.2%} {operator} {threshold:.2%}。", findings=[_finding(numerator, f"{numerator_name}/{denominator_name}={ratio:.2%}")], metrics={"ratio": round(ratio, 6), "threshold": threshold})
    if evaluated:
        return _status_result(rule, Status.PASS, "结构化比例检查通过。", metrics={"evaluated_checks": evaluated})
    return _status_result(rule, Status.INSUFFICIENT_INPUT, "缺少执行结构化比例检查所需的数据。", missing=list(dict.fromkeys(missing)))


def _evaluate_absolute_money(rule: MatchedRule, formula: str, resolved: dict[str, ValueCandidate] | None = None) -> RuleResult | None:
    checks = list(_ABSOLUTE_MONEY.finditer(formula))
    if not checks:
        return None
    missing = []
    evaluated = 0
    for match in checks:
        field = _formula_field(match.group("field"))
        threshold = float(match.group("threshold"))
        operator = match.group("operator")
        if not _money_threshold_is_authoritative(rule, threshold) or not _operator_is_authoritative(rule, operator):
            return _status_result(rule, Status.WARNING, "派生的金额阈值或比较方向未能从重点排查情形/法规依据中复核，已停止自动判定。", metrics={"requires_review": True, "criterion_source": "unverified"})
        extracted = _money_value(field, rule, resolved)
        if extracted is None:
            missing.append(field)
            continue
        evaluated += 1
        current = float(extracted.value)
        violated = {">": current > threshold, ">=": current >= threshold, "<": current < threshold, "<=": current <= threshold}[operator]
        if violated:
            status = _trigger_status(formula, match.start(), match.end())
            return _status_result(rule, status, f"结构化金额检查触发：{current:g} {operator} {threshold:g}。", findings=[_finding(extracted, f"{field}触发规则阈值")], metrics={"value": current, "threshold": threshold})
    if evaluated:
        return _status_result(rule, Status.PASS, "结构化金额检查通过。", metrics={"evaluated_checks": evaluated})
    return _status_result(rule, Status.INSUFFICIENT_INPUT, "缺少执行结构化金额检查所需的数据。", missing=list(dict.fromkeys(missing)))


def _evaluate_percentages(rule: MatchedRule, formula: str, resolved: dict[str, ValueCandidate] | None = None) -> RuleResult | None:
    checks = list(_SCALAR_PERCENT.finditer(formula))
    if not checks:
        return None
    missing = []
    evaluated = 0
    for match in checks:
        field = _formula_field(match.group("field"))
        threshold = float(match.group("threshold"))
        operator = match.group("operator")
        if not _ratio_threshold_is_authoritative(rule, threshold) or not _operator_is_authoritative(rule, operator):
            return _status_result(rule, Status.WARNING, "派生的比例阈值或比较方向未能从重点排查情形/法规依据中复核，已停止自动判定。", metrics={"requires_review": True, "criterion_source": "unverified"})
        extracted = _percent_value(field, rule, resolved)
        if extracted is None:
            missing.append(field)
            continue
        evaluated += 1
        current = float(extracted.value)
        triggered = {">": current > threshold, ">=": current >= threshold, "<": current < threshold, "<=": current <= threshold}[operator]
        if triggered:
            status = _trigger_status(formula, match.start(), match.end())
            return _status_result(rule, status, f"结构化比例字段检查触发：{current:.2%} {operator} {threshold:.2%}。", findings=[_finding(extracted, f"{field}触发规则阈值")], metrics={"value": current, "threshold": threshold})
    if evaluated:
        return _status_result(rule, Status.PASS, "结构化比例字段检查通过。", metrics={"evaluated_checks": evaluated})
    return _status_result(rule, Status.INSUFFICIENT_INPUT, "缺少执行结构化比例字段检查所需的数据。", missing=list(dict.fromkeys(missing)))


def _evaluate_dates(rule: MatchedRule, formula: str, resolved: dict[str, ValueCandidate] | None = None) -> RuleResult | None:
    date_fields = [field for field in _field_names(rule) if "日期" in field or "时间" in field]
    if len(date_fields) < 2:
        return None
    threshold_match = re.search(r"<\s*(\d+)\s*(?:日|天|个工作日)?", formula)
    if threshold_match is None:
        threshold_match = re.search(r"(?:不少于|至少|≥)\s*(\d+)\s*(?:日|天|个工作日)?", formula)
    if not threshold_match:
        return None
    threshold = int(threshold_match.group(1))
    if not _date_threshold_is_authoritative(rule, threshold):
        return _status_result(rule, Status.WARNING, "派生的日期阈值未能从重点排查情形/法规依据中复核，已停止自动判定。", metrics={"requires_review": True, "criterion_source": "unverified"})
    first = _date_value(date_fields[0], rule, resolved)
    second = _date_value(date_fields[1], rule, resolved)
    missing = [field for field, value in zip(date_fields[:2], (first, second)) if value is None]
    if first is None or second is None:
        return _status_result(rule, Status.INSUFFICIENT_INPUT, "缺少执行日期区间检查所需的数据。", missing=missing)
    if re.search(r"截止日期\s*<=\s*[^\n]*结束日期", formula) and second.value <= first.value:
        return _status_result(rule, Status.VIOLATION, "截止日期未晚于发售结束日期。", findings=[_finding(second, "截止日期必须晚于发售结束日期")])
    days = abs((second.value - first.value).days)
    if "开始" in date_fields[0] and "结束" in date_fields[1]:
        days += 1
    if days < threshold:
        status = _trigger_status(formula, threshold_match.start(), threshold_match.end())
        return _status_result(rule, status, f"日期间隔为 {days} 天，低于规则要求的 {threshold} 天。", findings=[_finding(second, f"日期间隔不足 {threshold} 天")], metrics={"days": days, "threshold_days": threshold})
    return _status_result(rule, Status.PASS, f"日期间隔为 {days} 天，满足不少于 {threshold} 天的要求。", metrics={"days": days, "threshold_days": threshold})


def _value_candidates(rule: MatchedRule) -> list[ValueCandidate]:
    candidates: list[ValueCandidate] = []
    patterns = (("money", _MONEY), ("percent", _PERCENT), ("date", _DATE))
    for evidence_index, evidence in enumerate(rule.evidence):
        for line in evidence.text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            matches = sorted(((kind, match) for kind, pattern in patterns for match in pattern.finditer(stripped)), key=lambda item: item[1].start())
            for target_index, (kind, match) in enumerate(matches):
                if kind == "money":
                    number = float(match.group("value").replace(",", ""))
                    multiplier = {"元": 1.0, "万": 10000.0, "万元": 10000.0, "亿元": 100000000.0}[match.group("unit")]
                    value: float | datetime = number * multiplier
                elif kind == "percent":
                    value = float(match.group("value")) / 100.0
                else:
                    value = datetime(int(match.group("year")), int(match.group("month")), int(match.group("day")), int(match.group("hour") or 0), int(match.group("minute") or 0))
                parts: list[str] = []
                cursor = 0
                for index, (_other_kind, other) in enumerate(matches):
                    if other.start() < cursor:
                        continue
                    parts.extend((stripped[cursor:other.start()], "<VALUE>" if index == target_index else "<OTHER_VALUE>"))
                    cursor = other.end()
                parts.append(stripped[cursor:])
                candidates.append(ValueCandidate(kind=kind, value=value, evidence_index=evidence_index, quote=match.group(0), context="".join(parts)[:240]))
    return candidates[:80]


def _expected_numeric_fields(rule: MatchedRule, formula: str) -> list[str]:
    fields = [field for field in _field_names(rule) if any(marker in field for marker in ("金额", "估算价", "预算", "比例", "日期", "时间"))]
    for pattern in (_RATIO, _ABSOLUTE_MONEY, _SCALAR_PERCENT):
        for match in pattern.finditer(formula):
            for name, value in match.groupdict().items():
                if name in {"numerator", "denominator", "field"} and value:
                    fields.append(_formula_field(value))
    return list(dict.fromkeys(fields))


def _evaluate_supported(rule: MatchedRule, formula: str, resolved: dict[str, ValueCandidate] | None = None) -> RuleResult:
    results = []
    for evaluator in (_evaluate_ratios, _evaluate_absolute_money, _evaluate_percentages, _evaluate_dates):
        result = evaluator(rule, formula, resolved)
        if result is not None:
            results.append(result)
    for status in (Status.VIOLATION, Status.WARNING):
        for result in results:
            if result.status == status:
                return result
    insufficient = [result for result in results if result.status == Status.INSUFFICIENT_INPUT]
    if insufficient:
        missing = list(dict.fromkeys(value for result in insufficient for value in result.missing_inputs))
        return _status_result(rule, Status.INSUFFICIENT_INPUT, "正则尚未定位到部分预设字段。", missing=missing)
    if results and all(result.status == Status.PASS for result in results):
        return _status_result(rule, Status.PASS, "所有从重点排查情形/法规依据派生的可解析结构化子条件均检查通过。", metrics={"evaluated_subchecks": len(results)})
    return _status_result(rule, Status.WARNING, "重点排查情形未提供当前通用执行器可确认的定量条件，需进行语义或人工复核。", metrics={"requires_review": True})


def evaluate_structured(rule: MatchedRule, *, enable_semantic_aliases: bool = False) -> RuleResult:
    """正则提取数值；模型可选地只负责把近义字段映射到正则候选位置。"""
    if not rule.evidence:
        return _status_result(rule, Status.WARNING, "内容匹配阶段未定位到结构化检查原文，不能据此认定输入资料缺失。", metrics={"reason": "evidence_not_retrieved"})
    formula = _derived_plan(rule)
    if not formula:
        return _evaluate_supported(rule, formula)
    fields = _expected_numeric_fields(rule, formula)
    candidates = _value_candidates(rule)
    if enable_semantic_aliases and fields and len(candidates) > 1:
        try:
            resolved = resolve_field_values(rule, fields, candidates)
        except Exception as exc:
            return _status_result(rule, Status.WARNING, "预设字段未能与原文中的近义字段可靠对应，需人工复核。", metrics={"requires_review": True, "field_mapping_error": f"{type(exc).__name__}: {exc}"})
        result = _evaluate_supported(rule, formula, resolved)
        if result.status == Status.INSUFFICIENT_INPUT:
            return _status_result(rule, Status.WARNING, "正则已扫描证据，语义字段映射后仍无法取得全部操作数；这不等同于缺少规则输入。", metrics={"requires_review": True, "resolved_fields": sorted(resolved)})
        return replace(result, metrics={**result.metrics, "semantic_field_aliases": sorted(resolved)})
    result = _evaluate_supported(rule, formula)
    if result.status == Status.INSUFFICIENT_INPUT:
        return _status_result(rule, Status.WARNING, "正则未能可靠取得全部结构化操作数；这不等同于缺少规则输入。", metrics={"requires_review": True, "unresolved_fields": result.missing_inputs})
    return result
