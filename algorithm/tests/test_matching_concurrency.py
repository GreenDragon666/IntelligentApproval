from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from src.cont_match.llm_matcher import _candidate_excerpt
from src.cont_match.pipeline import prepare_case
from src.page_schema import PolicyRule


class MatchingConcurrencyTest(unittest.TestCase):
    def test_llm_excerpt_focuses_on_rule_match_in_late_section_text(self) -> None:
        rule = PolicyRule(rule_id=1, rule_raw="投标保证金比例不得超过限制", rule_text="生成内容")
        text = "无关内容" * 500 + "投标保证金比例不得超过限制" + "尾部" * 500
        excerpt = _candidate_excerpt(rule, text, 120)
        self.assertIn("投标保证金比例不得超过限制", excerpt)

    def test_llm_candidate_selection_runs_concurrently_and_keeps_method(self) -> None:
        active = 0
        peak = 0
        lock = threading.Lock()

        def select(_rule, candidates, *, max_selected):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.03)
            with lock:
                active -= 1
            return candidates[:max_selected]

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report = root / "report.txt"
            report.write_text("第一章 项目概况\n招标文件项目内容和评标办法。", encoding="utf-8")
            rules_path = root / "rules.json"
            rules_path.write_text(json.dumps([{"rule_id": index, "rule_raw": "项目内容", "rule_text": "检查项目内容", "check_method": "大模型分析"} for index in range(1, 5)], ensure_ascii=False), encoding="utf-8")
            with patch("src.cont_match.pipeline.select_candidates", side_effect=select):
                case = prepare_case(case_id="report_1", report_path=report, rules_path=rules_path, output_path=root / "matched.json", use_embedding=False, use_llm=True, strict_llm=True, match_workers=4, candidate_count=1, evidence_count=1, minimum_score=0)
        self.assertGreater(peak, 1)
        self.assertTrue(all(rule.check_method == "大模型分析" for rule in case.rules))

    def test_empty_llm_selection_keeps_lexical_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report = root / "report.txt"
            report.write_text("第一章 评标办法\n评分标准应当明确具体。", encoding="utf-8")
            rules_path = root / "rules.json"
            rules_path.write_text(json.dumps([{"rule_id": 1, "rule_raw": "评分标准是否明确", "rule_text": "生成内容", "check_method": "大模型分析"}], ensure_ascii=False), encoding="utf-8")
            with patch("src.cont_match.pipeline.select_candidates", return_value=[]):
                case = prepare_case(case_id="report_1", report_path=report, rules_path=rules_path, output_path=root / "matched.json", use_embedding=False, use_llm=True, strict_llm=True, candidate_count=1, evidence_count=1, minimum_score=0)
        self.assertEqual(len(case.rules[0].evidence), 1)

    @patch("src.cont_match.pipeline.HybridSectionMatcher", side_effect=RuntimeError("模型目录不存在"))
    def test_embedding_failure_is_visible_and_falls_back_to_lexical(self, _hybrid) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report = root / "report.txt"
            report.write_text("第一章 评标办法\n评分标准应当明确具体。", encoding="utf-8")
            rules_path = root / "rules.json"
            rules_path.write_text(json.dumps([{"rule_id": 1, "rule_raw": "评分标准是否明确", "rule_text": "生成内容"}], ensure_ascii=False), encoding="utf-8")
            artifacts = root / "artifacts"
            case = prepare_case(case_id="report_1", report_path=report, rules_path=rules_path, output_path=root / "matched.json", artifacts_dir=artifacts, use_embedding=True, candidate_count=1, evidence_count=1, minimum_score=0)
            manifest = json.loads((artifacts / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(len(case.rules[0].evidence), 1)
        self.assertEqual(manifest["retrieval_method"], "lexical")
        self.assertIn("模型目录不存在", manifest["embedding_error"])


if __name__ == "__main__":
    unittest.main()
