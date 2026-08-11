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
        chat.return_value = json.dumps({"status": "violation", "summary": "评分标准未细化", "legal_basis": "", "findings": [{"evidence_index": 0, "quote": "技术方案优秀得10分", "reason": "仅给出主观等级"}], "confidence": 0.91, "missing_inputs": []}, ensure_ascii=False)
        evaluation = evaluate_semantic(self.rule)
        self.assertEqual(evaluation.result.status, Status.VIOLATION)
        self.assertEqual(evaluation.attempts, 1)
        self.assertIn("/no_think", chat.call_args.args[0])

    @patch("src.rule_check.semantic.llm.chat")
    def test_invalid_quote_is_retried(self, chat) -> None:
        invalid = {"status": "violation", "summary": "x", "findings": [{"evidence_index": 0, "quote": "不存在的原文", "reason": "x"}], "confidence": 0.8, "missing_inputs": []}
        valid = {"status": "pass", "summary": "未明确触发", "findings": [], "confidence": 0.7, "missing_inputs": []}
        chat.side_effect = [json.dumps(invalid, ensure_ascii=False), json.dumps(valid, ensure_ascii=False)]
        evaluation = evaluate_semantic(self.rule)
        self.assertEqual(evaluation.result.status, Status.PASS)
        self.assertEqual(evaluation.attempts, 2)


if __name__ == "__main__":
    unittest.main()
