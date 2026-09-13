from __future__ import annotations

import unittest
from unittest.mock import patch

from src.rule_check.field_resolver import ValueCandidate
from src.rule_check.structured import evaluate_structured
from src.rule_schema import EvidenceLocation, MatchedEvidence, MatchedRule, PageRange, Status


LOCATION = EvidenceLocation(file="test.pdf", section="测试章节", pdf_pages=PageRange(1, 1))


def _rule(rule_text: str, text: str, fields: str, rule_id: int = 1, rule_raw: str = "结构化测试") -> MatchedRule:
    return MatchedRule(rule_id=rule_id, rule_raw=rule_raw, rule_text=rule_text, evidence=[MatchedEvidence(LOCATION, text)], check_method="结构化数据检查", structured_fields=fields)


class StructuredExecutorTest(unittest.TestCase):
    def test_cash_only_performance_guarantee_is_violation(self) -> None:
        rule = _rule("【法规依据】不得限定经营主体缴纳保证金的形式。", "履约保证金须以现金形式提交，不接受银行保函或保险保单。", "", rule_id=3, rule_raw="限定履约保证金只能以现金形式提交")
        result = evaluate_structured(rule)
        self.assertEqual(result.status, Status.VIOLATION)
        self.assertTrue(result.metrics["policy_checker"])

    def test_cash_or_guarantee_is_not_cash_only(self) -> None:
        rule = _rule("【法规依据】不得限定经营主体缴纳保证金的形式。", "履约保证金的形式：银行转账等现金形式或者银行保函等非现金形式。", "", rule_id=3, rule_raw="限定履约保证金只能以现金形式提交")
        self.assertEqual(evaluate_structured(rule).status, Status.PASS)

    def test_project_specific_two_day_publicity_overrides_generic_three_days(self) -> None:
        text = "通用条款：中标候选人公示期不得少于3日。\n投标人须知前附表：中标候选人公示期为2个工作日。"
        rule = _rule("【法规依据】公示期不得少于3日。", text, "", rule_id=4, rule_raw="中标候选人公示期不足3日")
        result = evaluate_structured(rule)
        self.assertEqual(result.status, Status.VIOLATION)
        self.assertEqual(result.metrics["days"], 2)

    def test_advance_payment_policy_handles_zero_and_valid_percentage(self) -> None:
        zero = _rule("【法规依据】预付比例不低于10%，不高于30%。", "本项目不支付预付款。", "", rule_id=5, rule_raw="施工项目预付款不得低于10%")
        valid = _rule("【法规依据】预付比例不低于10%，不高于30%。", "开工预付款金额：20%签约合同价。", "", rule_id=5, rule_raw="施工项目预付款不得低于10%")
        self.assertEqual(evaluate_structured(zero).status, Status.VIOLATION)
        self.assertEqual(evaluate_structured(valid).status, Status.PASS)

    def test_advance_payment_major_project_exception_requires_review(self) -> None:
        rule = _rule("【法规依据】重大工程项目按年度工程计划逐年预付。", "本项目为重大工程项目，按年度工程计划逐年预付5%。", "", rule_id=5, rule_raw="施工项目预付款不得低于10%")
        result = evaluate_structured(rule)
        self.assertEqual(result.status, Status.WARNING)
        self.assertTrue(result.metrics["major_project_exception"])

    def test_money_ratio_violation(self) -> None:
        rule = _rule("【公式】IF 投标保证金金额/项目估算价 > 0.02 OR 投标保证金金额 > 800000 THEN 标记为违规", "投标保证金金额：10万元\n合同估算价：300万元", "投标保证金金额字段、项目估算价字段", rule_raw="投标保证金不得超过项目估算价的2%，且不得超过80万元")
        result = evaluate_structured(rule)
        self.assertEqual(result.status, Status.VIOLATION)
        self.assertAlmostEqual(result.metrics["ratio"], 1 / 30, places=5)
        self.assertEqual(result.findings[0].quote, "10万元")

    def test_two_labeled_amounts_on_same_line_are_not_confused(self) -> None:
        rule = _rule("【公式】IF 投标保证金金额/项目估算价 > 0.02 THEN 标记为违规", "投标保证金金额：10万元；合同估算价：300万元", "投标保证金金额字段、项目估算价字段", rule_raw="投标保证金不得超过项目估算价的2%")
        result = evaluate_structured(rule)
        self.assertEqual(result.status, Status.VIOLATION)
        self.assertAlmostEqual(result.metrics["ratio"], 1 / 30, places=5)

    def test_inclusive_sale_period_passes_five_days(self) -> None:
        rule = _rule("【公式】IF (招标文件.发售结束日期 - 招标文件.发售开始日期) < 5 THEN 标记为违规", "招标文件获取时间：2025 年02 月13 日00 时00 分至2025 年02 月17 日23 时59 分", "招标文件发售开始日期、招标文件发售结束日期", rule_raw="招标文件获取时间不得少于5日")
        result = evaluate_structured(rule)
        self.assertEqual(result.status, Status.PASS)
        self.assertEqual(result.metrics["evaluated_subchecks"], 1)

    def test_cross_document_rule_is_not_guessed(self) -> None:
        rule = _rule("【公式】IF 澄清公告.发布状态 = '未发布' OR 澄清公告.内容 <> 异议答复.内容 THEN 标记为违规", "招标文件规定投标人可提出异议。", "异议记录、澄清公告发布状态、异议答复内容")
        result = evaluate_structured(rule)
        self.assertEqual(result.status, Status.WARNING)
        self.assertEqual(result.missing_inputs, [])

    def test_generated_threshold_is_not_authoritative(self) -> None:
        rule = _rule("【公式】IF 投标保证金金额/项目估算价 > 0.02 THEN 标记为违规", "投标保证金金额：10万元\n合同估算价：300万元", "投标保证金金额字段、项目估算价字段")
        result = evaluate_structured(rule)
        self.assertEqual(result.status, Status.WARNING)
        self.assertTrue(result.metrics["requires_review"])

    def test_legal_basis_can_supply_numeric_criterion(self) -> None:
        rule_text = "【描述】宏观描述\n【法规依据】《实施条例》规定：履约保证金不得超过中标合同金额的10%。\n【公式】IF 履约保证金金额/合同金额 > 0.9 THEN 标记为违规\n【开发说明】需要虚构字段"
        rule = _rule(rule_text, "履约保证金金额：20万元\n中标合同金额：100万元", "履约保证金金额字段、合同金额字段", rule_raw="履约保证金设置是否合规")
        result = evaluate_structured(rule)
        self.assertEqual(result.status, Status.VIOLATION)
        self.assertAlmostEqual(result.metrics["ratio"], 0.2)
        self.assertAlmostEqual(result.metrics["threshold"], 0.1)

    def test_generated_operator_is_ignored_in_favor_of_rule_raw(self) -> None:
        rule = _rule("【公式】IF 投标保证金金额/项目估算价 < 0.02 THEN 标记为违规", "投标保证金金额：1万元\n合同估算价：300万元", "投标保证金金额字段、项目估算价字段", rule_raw="投标保证金不得超过项目估算价的2%")
        result = evaluate_structured(rule)
        self.assertEqual(result.status, Status.PASS)

    @patch("src.rule_check.structured.resolve_field_values")
    def test_semantic_alias_only_selects_regex_value_candidate(self, resolve) -> None:
        def choose(_rule, fields, candidates):
            self.assertIn("投标保证金金额", fields)
            self.assertTrue(all(isinstance(candidate, ValueCandidate) for candidate in candidates))
            self.assertTrue(all("10万元" not in candidate.context and "300万元" not in candidate.context for candidate in candidates))
            return {"投标保证金金额": candidates[0], "项目估算价": candidates[1]}

        resolve.side_effect = choose
        rule = _rule("【公式】IF 投标保证金金额/项目估算价 > 0.02 THEN 标记为违规", "担保金：10万元\n采购预算：300万元", "投标保证金金额字段、项目估算价字段", rule_raw="投标保证金不得超过项目估算价的2%")
        result = evaluate_structured(rule, enable_semantic_aliases=True)
        self.assertEqual(result.status, Status.VIOLATION)
        self.assertEqual(result.findings[0].quote, "10万元")

    @patch("src.rule_check.structured.resolve_field_values")
    def test_partial_semantic_mapping_does_not_fall_back_to_ambiguous_values(self, resolve) -> None:
        resolve.side_effect = lambda _rule, _fields, candidates: {"投标保证金金额": candidates[0]}
        rule = _rule("【公式】IF 无关公式 > 9 THEN 违规", "投标保证金金额：10万元；合同估算价：300万元", "投标保证金金额字段、项目估算价字段", rule_raw="投标保证金不得超过项目估算价的2%")
        result = evaluate_structured(rule, enable_semantic_aliases=True)
        self.assertEqual(result.status, Status.WARNING)
        self.assertTrue(result.metrics["requires_review"])


if __name__ == "__main__":
    unittest.main()
