"""统一入口的参数、自动编号和 PDF 发现测试。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from main import _allocate_report_dir, _build_parser, _default_output, _discover_pdfs


class MainEntryTest(unittest.TestCase):
    def test_existing_json_mode_keeps_step_three_entry(self) -> None:
        args = _build_parser().parse_args(["--input", "case/rules_matched.json"])
        self.assertEqual(args.input, "case/rules_matched.json")
        self.assertIsNone(args.one_report_path)
        self.assertIsNone(args.reports_path)

    def test_single_pdf_mode_uses_one_report_path(self) -> None:
        args = _build_parser().parse_args(["--one_report_path", "incoming/tender.pdf", "--policy-rules", "policy.xlsx"])
        self.assertEqual(args.one_report_path, "incoming/tender.pdf")
        self.assertIsNone(args.reports_path)

    def test_directory_mode_uses_reports_path(self) -> None:
        args = _build_parser().parse_args(["--reports_path", "incoming", "--policy-rules", "policy.xlsx", "--use-llm"])
        self.assertEqual(args.reports_path, "incoming")
        self.assertTrue(args.use_llm)

    def test_allocate_report_dir_uses_max_existing_number(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "reports"
            root.mkdir()
            (root / "report1").mkdir()
            (root / "report_3").mkdir()
            allocated = _allocate_report_dir(root)
            self.assertEqual(allocated.name, "report_4")
            self.assertTrue(allocated.is_dir())

    def test_discover_pdfs_is_recursive_and_excludes_output_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            incoming = root / "incoming"
            nested = incoming / "nested"
            output = incoming / "reports" / "report_1"
            nested.mkdir(parents=True)
            output.mkdir(parents=True)
            (incoming / "a.pdf").touch()
            (nested / "B.PDF").touch()
            (nested / "note.txt").touch()
            (output / "generated.pdf").touch()
            discovered = _discover_pdfs(incoming, incoming / "reports")
            self.assertEqual([path.name for path in discovered], ["a.pdf", "B.PDF"])

    def test_default_report_path_follows_case_layout(self) -> None:
        matched = Path("reports/report_1/matched/rules_matched.json")
        self.assertEqual(_default_output(matched), Path("reports/report_1/results"))


if __name__ == "__main__":
    unittest.main()
