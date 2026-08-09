from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.preprocess import prepare_case
from src.preprocess.pdf import extract_pdf_pages
from src.preprocess.rules import load_policy_rules
from src.rule_schema import MatchedCase


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports" / "report_2"
PDF = REPORT / "招标文件2.pdf"
RULE_JSON = REPORT / "matched" / "rules_matched.json"
RULE_XLSX = REPORT / "规则-招标文件2对应内容-全量校正.xlsx"


class PreprocessTest(unittest.TestCase):
    def test_real_rule_sources(self) -> None:
        from_json = load_policy_rules(RULE_JSON)
        from_xlsx = load_policy_rules(RULE_XLSX)
        self.assertEqual(len(from_json), 41)
        self.assertEqual(len(from_xlsx), 41)
        self.assertIsInstance(from_xlsx[0].rule_id, int)
        self.assertEqual(from_xlsx[0].rule_raw, from_json[0].rule_raw)
        self.assertTrue(from_xlsx[0].match_hints)

    def test_real_pdf_dual_page_numbers(self) -> None:
        pages = extract_pdf_pages(PDF, document_page_1_pdf_page=9)
        self.assertEqual(len(pages), 204)
        self.assertIsNone(pages[7].document_page)
        self.assertEqual(pages[8].pdf_page, 9)
        self.assertEqual(pages[8].document_page, 1)

    def test_no_model_pipeline_writes_formal_json(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "rules_matched.json"
            artifacts = root / "artifacts"
            case = prepare_case(
                case_id="report_2_preprocess_test",
                pdf_path=PDF,
                rules_path=RULE_XLSX,
                output_path=output,
                artifacts_dir=artifacts,
                document_page_1_pdf_page=9,
                use_llm=False,
            )
            loaded = MatchedCase.from_json_file(output)
            raw = json.loads(output.read_text(encoding="utf-8"))
            manifest = json.loads(
                (artifacts / "manifest.json").read_text(encoding="utf-8")
            )

            self.assertEqual(case, loaded)
            self.assertEqual(len(loaded.rules), 41)
            self.assertEqual(set(raw["source"]), {"file"})
            self.assertEqual(manifest["pdf_page_count"], 204)
            self.assertEqual(manifest["rule_count"], 41)
            self.assertTrue((artifacts / "outline.json").is_file())
            self.assertTrue((artifacts / "sections.json").is_file())
            self.assertTrue((artifacts / "matches.json").is_file())
            evidence = next(rule.evidence[0] for rule in loaded.rules if rule.evidence)
            self.assertIn("[PDF第", evidence.text)
            self.assertGreaterEqual(evidence.location.pdf_pages.start, 1)


if __name__ == "__main__":
    unittest.main()
