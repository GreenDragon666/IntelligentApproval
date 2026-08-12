from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from src.rule_check.semantic import evaluate_semantic
from src.rule_schema import EvidenceLocation, MatchedEvidence, MatchedRule, PageRange, Status


class SemanticExecutorTest(unittest.TestCase):
    def setUp(self) -> None:
        location = EvidenceLocation(file="test.pdf", section="评标办法", pdf_pages=PageRange(3, 3))
        self.rule = MatchedRule(rule_id=2, rule_raw="评分标准是否明确", rule_text="主观评分标准未细化时违规", evidence=[MatchedEvidence(location, "技术方案优秀得10分，未说明分档标准。")], check_method="关键词匹配+大模型分析")

    @patch("src.rule_check.semantic.llm.chat")
    def test_valid_structured_llm_result(self, chat) -> None:
        chat.return_value = json.dumps({"status": "violation", "summary": "评分标准未细化", "analysis": "证据只给出优秀档分值，未说明可操作的分档条件，因此违规结论与规则一致。", "legal_basis": "", "findings": [{"evidence_index": 0, "quote": "技术方案优秀得10分", "reason": "仅给出主观等级"}], "confidence": 0.91, "missing_inputs": []}, ensure_ascii=False)
        evaluation = evaluate_semantic(self.rule)
        self.assertEqual(evaluation.result.status, Status.VIOLATION)
        self.assertIn("违规结论", evaluation.result.analysis)
        self.assertEqual(evaluation.attempts, 1)
        self.assertIn("/no_think", chat.call_args.args[0])

    @patch("src.rule_check.semantic.llm.chat")
    def test_payload_includes_legal_basis_but_excludes_formula(self, chat) -> None:
        self.rule = MatchedRule(rule_id=2, rule_raw="检查期限", rule_text="【描述】检查公告期限是否充分。\n【法规依据】法定期限至少5日。\n【公式】IF 虚构字段 < 99 THEN 违规\n【开发说明】虚构输入表", evidence=self.rule.evidence, check_method="大模型分析")
        chat.return_value = json.dumps({"status": "pass", "summary": "未触发", "analysis": "证据未触发期限违规，当前可判为通过。", "legal_basis": "法定期限至少5日。", "findings": [], "confidence": 0.8, "missing_inputs": []}, ensure_ascii=False)
        evaluate_semantic(self.rule)
        prompt = chat.call_args.args[0]
        self.assertIn("检查公告期限是否充分", prompt)
        self.assertIn("法定期限至少5日", prompt)
        self.assertNotIn("虚构字段", prompt)
        self.assertNotIn("虚构输入表", prompt)

    @patch("src.rule_check.semantic.llm.chat")
    def test_invalid_quote_is_retried(self, chat) -> None:
        invalid = {"status": "violation", "summary": "x", "findings": [{"evidence_index": 0, "quote": "不存在的原文", "reason": "x"}], "confidence": 0.8, "missing_inputs": []}
        valid = {"status": "pass", "summary": "未明确触发", "analysis": "现有证据不足以支持违规，pass结论合理。", "findings": [], "confidence": 0.7, "missing_inputs": []}
        chat.side_effect = [json.dumps(invalid, ensure_ascii=False), json.dumps(valid, ensure_ascii=False)]
        evaluation = evaluate_semantic(self.rule)
        self.assertEqual(evaluation.result.status, Status.PASS)
        self.assertEqual(evaluation.attempts, 2)

    @patch("src.rule_check.semantic.llm.chat")
    def test_pdf_whitespace_quote_is_mapped_back_to_source(self, chat) -> None:
        self.rule = MatchedRule(rule_id=2, rule_raw="评分标准是否明确", rule_text="【法规依据】评标标准应明确。", evidence=[MatchedEvidence(self.rule.evidence[0].location, "技术方案优 秀得10分，未说明分档标准。")], check_method="大模型分析")
        chat.return_value = json.dumps({"status": "violation", "summary": "评分标准未细化", "analysis": "证据中的评分标准不可操作，因此违规结论合理。", "findings": [{"evidence_index": 0, "quote": "技术方案优秀得10分", "reason": "未细化"}], "confidence": 0.9, "missing_inputs": []}, ensure_ascii=False)
        evaluation = evaluate_semantic(self.rule)
        self.assertEqual(evaluation.result.findings[0].quote, "技术方案优 秀得10分")

    @patch("src.rule_check.semantic.llm.chat")
    def test_pass_discards_explanatory_findings(self, chat) -> None:
        chat.return_value = json.dumps({"status": "pass", "summary": "已明确", "analysis": "现有证据支持通过。", "findings": [{"evidence_index": 0, "quote": "技术方案优秀得10分", "reason": "说明性引用"}], "confidence": 0.7, "missing_inputs": []}, ensure_ascii=False)
        evaluation = evaluate_semantic(self.rule)
        self.assertEqual(evaluation.result.status, Status.PASS)
        self.assertEqual(evaluation.result.findings, [])


if __name__ == "__main__":
    unittest.main()
