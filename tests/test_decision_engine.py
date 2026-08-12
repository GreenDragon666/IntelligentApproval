from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from src.engine import run_case
from src.rule_check.semantic import SemanticEvaluation
from src.rule_check.explainer import ResultExplanation
from src.rule_schema import EvidenceLocation, MatchedCase, MatchedEvidence, MatchedRule, PageRange, RuleResult, SourceDocument, Status


class DecisionEngineTest(unittest.TestCase):
    def _case(self) -> MatchedCase:
        location = EvidenceLocation(file="test.pdf", section="章节", pdf_pages=PageRange(1, 1))
        rule = MatchedRule(rule_id=1, rule_raw="语义规则", rule_text="判断是否明确", evidence=[MatchedEvidence(location, "内容明确。")], check_method="大模型分析")
        return MatchedCase(case_id="report_1", source=SourceDocument("test.pdf"), rules=[rule])

    @patch("src.engine.evaluate_semantic")
    def test_success_is_cached_and_reused(self, evaluate) -> None:
        evaluate.return_value = SemanticEvaluation(RuleResult(rule_id=1, status=Status.PASS, summary="通过", analysis="证据支持通过。", confidence=0.9), 1)
        with tempfile.TemporaryDirectory() as temporary:
            first = run_case(self._case(), cache_dir=temporary, max_workers=2)
            second = run_case(self._case(), cache_dir=temporary, max_workers=2)
        self.assertFalse(first.rules[0].cached)
        self.assertTrue(second.rules[0].cached)
        self.assertEqual(evaluate.call_count, 1)

    @patch("src.engine.evaluate_semantic")
    def test_force_recheck_keeps_history_and_rollback_restores(self, evaluate) -> None:
        evaluate.side_effect = [SemanticEvaluation(RuleResult(rule_id=1, status=Status.PASS, summary="第一版", analysis="第一版分析", confidence=0.8), 1), SemanticEvaluation(RuleResult(rule_id=1, status=Status.WARNING, summary="第二版", analysis="第二版分析", confidence=0.7), 1)]
        with tempfile.TemporaryDirectory() as temporary:
            run_case(self._case(), cache_dir=temporary)
            run_case(self._case(), cache_dir=temporary, force_recheck=True)
            restored = run_case(self._case(), cache_dir=temporary, rollback_rule_ids=[1])
            self.assertTrue(list((Path(temporary) / "history").glob("*.json")))
        self.assertEqual(restored.rules[0].result.summary, "第一版")

    @patch("src.engine.evaluate_semantic")
    def test_no_llm_diagnostic_does_not_poison_later_cache(self, evaluate) -> None:
        evaluate.return_value = SemanticEvaluation(RuleResult(rule_id=1, status=Status.PASS, summary="模型已判定", analysis="模型分析", confidence=0.9), 1)
        with tempfile.TemporaryDirectory() as temporary:
            diagnostic = run_case(self._case(), cache_dir=temporary, enable_llm=False)
            normal = run_case(self._case(), cache_dir=temporary, enable_llm=True)
        self.assertEqual(diagnostic.rules[0].result.status, Status.INSUFFICIENT_INPUT)
        self.assertEqual(normal.rules[0].result.summary, "模型已判定")
        self.assertEqual(evaluate.call_count, 1)

    @patch("src.engine.explain_result")
    @patch("src.engine.evaluate_structured")
    def test_structured_result_gets_llm_explanation_without_status_override(self, evaluate, explain) -> None:
        case = self._case()
        case.rules[0] = replace(case.rules[0], check_method="结构化数据检查")
        deterministic = RuleResult(rule_id=1, status=Status.PASS, summary="正则检查通过")
        explained = RuleResult(rule_id=1, status=Status.PASS, summary="正则检查通过", analysis="数值低于法规上限，因此结果合理。")
        evaluate.return_value = deterministic
        explain.return_value = ResultExplanation(explained, 1)
        with tempfile.TemporaryDirectory() as temporary:
            report = run_case(case, cache_dir=temporary)
        self.assertEqual(report.rules[0].result.status, Status.PASS)
        self.assertIn("结果合理", report.rules[0].result.analysis)
        explain.assert_called_once_with(case.rules[0], deterministic)

    @patch("src.engine.evaluate_semantic")
    @patch("src.engine.evaluate_structured")
    def test_structured_requires_review_uses_semantic_adjudication(self, evaluate_structured, evaluate_semantic) -> None:
        case = self._case()
        case.rules[0] = replace(case.rules[0], check_method="结构化数据检查")
        initial = RuleResult(rule_id=1, status=Status.WARNING, summary="正则未取得完整操作数", metrics={"requires_review": True})
        final = RuleResult(rule_id=1, status=Status.PASS, summary="语义复核未发现违规", analysis="证据没有触发规则限制。", confidence=0.8)
        evaluate_structured.return_value = initial
        evaluate_semantic.return_value = SemanticEvaluation(final, 1)

        with tempfile.TemporaryDirectory() as temporary:
            report = run_case(case, cache_dir=temporary)

        run = report.rules[0]
        self.assertEqual(run.structured_result, initial)
        self.assertEqual(run.result.status, Status.PASS)
        self.assertTrue(run.result.metrics["structured_fallback"])
        self.assertEqual(run.result.metrics["structured_status"], "warning")
        self.assertEqual(run.error, "")


if __name__ == "__main__":
    unittest.main()
