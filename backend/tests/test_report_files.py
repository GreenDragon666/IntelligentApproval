from __future__ import annotations

import unittest

from app.services.report_files import render_brief


class ReportFileTests(unittest.TestCase):
    def test_brief_contains_document_and_rule_sections(self) -> None:
        text = render_brief({
            "reviewId": "review-1",
            "completedDocuments": 1,
            "failedDocuments": 0,
            "executionFailedCount": 0,
            "counts": {"passed": 1, "warning": 0, "violation": 0, "insufficient": 0},
            "documents": [{
                "fileName": "招标文件.pdf",
                "overallConclusion": "passed",
                "counts": {"passed": 1, "warning": 0, "violation": 0, "insufficient": 0, "executionFailed": 0},
                "rules": [{"number": 1, "title": "规则内容", "status": "passed"}],
            }],
        })
        self.assertIn("招标文件.pdf", text)
        self.assertIn("规则 1：规则内容", text)


if __name__ == "__main__":
    unittest.main()

