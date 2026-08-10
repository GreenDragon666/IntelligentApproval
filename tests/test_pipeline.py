"""使用 report_2 的正式 JSON 验证无模型执行路径。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.code_gen.checker_store import checker_key
from src.engine import run_case
from src.rule_schema import MatchedCase, Status


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CASE_PATH = PROJECT_ROOT / "reports/report_2/matched/rules_matched.json"


@unittest.skipUnless(CASE_PATH.is_file(), "本地未提供 report_2 正式匹配 JSON")
class PipelineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.case = MatchedCase.from_json_file(CASE_PATH)

    def test_formal_input_contract(self) -> None:
        self.assertEqual(self.case.case_id, "report_2")
        self.assertEqual(self.case.source.file, "招标文件2.pdf")
        self.assertEqual(len(self.case.rules), 41)
        self.assertEqual([rule.rule_id for rule in self.case.rules], list(range(1, 42)))

    def test_checker_key_is_stable(self) -> None:
        rule = self.case.get_rule(2)
        self.assertEqual(checker_key(rule), checker_key(rule))
        self.assertTrue(checker_key(rule).startswith("rule_2_"))

    def test_no_model_path_reports_missing_checker_and_empty_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as checker_dir:
            report = run_case(
                self.case,
                rule_ids=[2, 18],
                generate_missing=False,
                checker_dir=checker_dir,
            )
        self.assertEqual(report.overall, "partial")
        self.assertEqual(report.rules[0].result.status, Status.ERROR)
        self.assertEqual(report.rules[1].result.status, Status.INSUFFICIENT_INPUT)
        self.assertEqual(report.rules[1].checker_key, "")


if __name__ == "__main__":
    unittest.main()
