from __future__ import annotations

import unittest

from src.rule_check.structured import evaluate_structured
from src.rule_schema import EvidenceLocation, MatchedEvidence, MatchedRule, PageRange, Status


LOCATION = EvidenceLocation(file="test.pdf", section="测试章节", pdf_pages=PageRange(1, 1))


def _rule(rule_text: str, text: str, fields: str, rule_id: int = 1) -> MatchedRule:
    return MatchedRule(rule_id=rule_id, rule_raw="结构化测试", rule_text=rule_text, evidence=[MatchedEvidence(LOCATION, text)], check_method="结构化数据检查", structured_fields=fields)


class StructuredExecutorTest(unittest.TestCase):
    def test_money_ratio_violation(self) -> None:
        rule = _rule("【公式】IF 投标保证金金额/项目估算价 > 0.02 OR 投标保证金金额 > 800000 THEN 标记为违规", "投标保证金金额：10万元\n合同估算价：300万元", "投标保证金金额字段、项目估算价字段")
        result = evaluate_structured(rule)
        self.assertEqual(result.status, Status.VIOLATION)
        self.assertAlmostEqual(result.metrics["ratio"], 1 / 30, places=5)
        self.assertEqual(result.findings[0].quote, "10万元")

    def test_two_labeled_amounts_on_same_line_are_not_confused(self) -> None:
        rule = _rule("【公式】IF 投标保证金金额/项目估算价 > 0.02 THEN 标记为违规", "投标保证金金额：10万元；合同估算价：300万元", "投标保证金金额字段、项目估算价字段")
        result = evaluate_structured(rule)
        self.assertEqual(result.status, Status.VIOLATION)
        self.assertAlmostEqual(result.metrics["ratio"], 1 / 30, places=5)

    def test_inclusive_sale_period_passes_five_days(self) -> None:
        rule = _rule("【公式】IF (招标文件.发售结束日期 - 招标文件.发售开始日期) < 5 THEN 标记为违规", "招标文件获取时间：2025 年02 月13 日00 时00 分至2025 年02 月17 日23 时59 分", "招标文件发售开始日期、招标文件发售结束日期")
        result = evaluate_structured(rule)
        self.assertEqual(result.status, Status.PASS)
        self.assertEqual(result.metrics["evaluated_subchecks"], 1)

    def test_cross_document_rule_is_not_guessed(self) -> None:
        rule = _rule("【公式】IF 澄清公告.发布状态 = '未发布' OR 澄清公告.内容 <> 异议答复.内容 THEN 标记为违规", "招标文件规定投标人可提出异议。", "异议记录、澄清公告发布状态、异议答复内容")
        result = evaluate_structured(rule)
        self.assertEqual(result.status, Status.INSUFFICIENT_INPUT)
        self.assertIn("澄清公告发布状态", result.missing_inputs)


if __name__ == "__main__":
    unittest.main()
