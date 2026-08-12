from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from src.rule_check.explainer import explain_result
from src.rule_schema import EvidenceLocation, MatchedEvidence, MatchedRule, PageRange, RuleResult, Status


class ResultExplainerTest(unittest.TestCase):
    @patch("src.rule_check.explainer.llm.chat")
    def test_accepts_qwen_empty_think_wrapper_before_json(self, chat) -> None:
        location = EvidenceLocation(file="test.pdf", section="合同条款", pdf_pages=PageRange(8, 8))
        rule = MatchedRule(
            rule_id=21,
            rule_raw="履约保证金设置是否合规",
            rule_text="【法规依据】履约保证金不得超过中标合同金额的10%。",
            evidence=[MatchedEvidence(location, "履约保证金为中标合同金额的10%。")],
            check_method="结构化数据检查",
        )
        result = RuleResult(rule_id=21, status=Status.WARNING, summary="正则未取得完整操作数。", metrics={"requires_review": True})
        chat.return_value = '<think>\n\n</think>\n\n{"consistent":true,"analysis":"招标文件给出了10%的比例要求，但没有提供可供正则计算的合同金额和履约保证金金额，因此当前只能预警并提示人工复核。","confidence":0.5}'

        explanation = explain_result(rule, result)

        self.assertTrue(explanation.result.metrics["llm_analysis_consistent"])
        self.assertIn("只能预警", explanation.result.analysis)
        self.assertEqual(explanation.attempts, 1)
        self.assertEqual(chat.call_count, 1)

    @patch("src.rule_check.explainer.llm.chat")
    def test_explains_without_changing_deterministic_status(self, chat) -> None:
        location = EvidenceLocation(file="test.pdf", section="投标人须知", pdf_pages=PageRange(5, 5))
        rule = MatchedRule(
            rule_id=1,
            rule_raw="投标保证金比例不得超过法定上限",
            rule_text="【描述】核验保证金是否过高。\n【法规依据】投标保证金不得超过项目估算价的2%。\n【公式】IF 生成字段 > 99 THEN 违规",
            evidence=[MatchedEvidence(location, "项目估算价1000万元，投标保证金10万元。")],
            check_method="结构化数据检查",
        )
        result = RuleResult(rule_id=1, status=Status.PASS, summary="比例检查通过。", metrics={"ratio": 0.01})
        chat.return_value = json.dumps({"consistent": True, "analysis": "保证金占估算价1%，未超过2%的法规上限，pass结果合理。", "confidence": 0.96}, ensure_ascii=False)

        explained = explain_result(rule, result).result

        self.assertEqual(explained.status, Status.PASS)
        self.assertIn("pass结果合理", explained.analysis)
        self.assertTrue(explained.metrics["llm_analysis_consistent"])
        prompt = chat.call_args.args[0]
        self.assertIn("核验保证金是否过高", prompt)
        self.assertIn("不得超过项目估算价的2%", prompt)
        self.assertNotIn("生成字段", prompt)


if __name__ == "__main__":
    unittest.main()
