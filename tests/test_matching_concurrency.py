from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from src.cont_match.pipeline import prepare_case


class MatchingConcurrencyTest(unittest.TestCase):
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
                case = prepare_case(case_id="report_1", report_path=report, rules_path=rules_path, output_path=root / "matched.json", use_llm=True, strict_llm=True, match_workers=4, candidate_count=1, evidence_count=1, minimum_score=0)
        self.assertGreater(peak, 1)
        self.assertTrue(all(rule.check_method == "大模型分析" for rule in case.rules))


if __name__ == "__main__":
    unittest.main()
