from __future__ import annotations

import unittest

from app.services.result_mapper import DocumentProjection, build_review_summary, map_document_detail


MATCHED = {
    "case_id": "case-1",
    "source": {"file": "招标文件.pdf"},
    "rules": [
        {
            "rule_id": 1,
            "rule_raw": "投标保证金不得超过项目估算价的2%",
            "rule_text": "法规依据",
            "evidence": [{
                "location": {
                    "file": "招标文件.pdf",
                    "section": "投标人须知",
                    "pdf_pages": {"start": 12, "end": 13},
                    "document_pages": {"start": 4, "end": 5},
                    "page_basis": "original_pdf",
                },
                "text": "投标保证金为100万元",
            }],
        },
        {"rule_id": 2, "rule_raw": "项目需求描述应当清晰", "rule_text": "法规依据", "evidence": []},
    ],
}

REPORT = {
    "case_id": "case-1",
    "source_file": "招标文件.pdf",
    "summary": {"violation": 1, "warning": 0, "pass": 0, "insufficient_input": 0, "error": 1},
    "rules": [
        {
            "rule_id": 1,
            "rule_raw": "投标保证金不得超过项目估算价的2%",
            "result": {
                "rule_id": 1,
                "status": "violation",
                "summary": "保证金比例超过限制",
                "analysis": "已取得两个操作数并完成比例计算。",
                "legal_basis": "《招标投标法实施条例》第二十六条",
                "findings": [{"evidence_index": 0, "quote": "投标保证金为100万元", "reason": "超过法定比例"}],
                "metrics": {"requires_review": False, "evaluated_subchecks": 1, "semantic_field_aliases": ["项目估算价"]},
                "confidence": 0.98,
                "missing_inputs": [],
            },
            "error": "",
        },
        {
            "rule_id": 2,
            "rule_raw": "项目需求描述应当清晰",
            "result": {"rule_id": 2, "status": "error", "summary": "规则校验执行失败。", "findings": [], "metrics": {}, "missing_inputs": []},
            "error": "semantic_llm 执行失败",
        },
    ],
}


class ResultMapperTests(unittest.TestCase):
    def test_algorithm_contract_maps_to_frontend_contract(self) -> None:
        detail, failures = map_document_detail(review_id="review-1", document_id="doc-1", file_name="招标文件.pdf", report=REPORT, matched_case=MATCHED)
        self.assertEqual(failures, 1)
        self.assertEqual(detail["overallConclusion"], "violation")
        self.assertEqual(detail["rules"][0]["status"], "violation")
        self.assertIn("PDF第12-13页，文件内页码4-5", detail["rules"][0]["evidenceLocations"])
        self.assertIn("超过法定比例", detail["rules"][0]["matchedText"])
        self.assertEqual(detail["rules"][0]["indicators"]["fieldAliases"], ["项目估算价"])
        self.assertEqual(detail["rules"][1]["status"], "insufficient")

    def test_review_summary_counts_failures_without_calling_them_valid(self) -> None:
        detail, failures = map_document_detail(review_id="review-1", document_id="doc-1", file_name="招标文件.pdf", report=REPORT, matched_case=MATCHED)
        summary = build_review_summary("review-1", [
            DocumentProjection("doc-1", "招标文件.pdf", "completed", detail, failures),
            DocumentProjection("doc-2", "损坏文件.pdf", "failed", None, 0, "无法提取文本"),
        ])
        self.assertEqual(summary["completedDocuments"], 1)
        self.assertEqual(summary["failedDocuments"], 1)
        self.assertEqual(summary["executionFailedCount"], 1)
        self.assertEqual(summary["validDecisionCount"], 1)
        self.assertEqual(summary["documents"][0]["counts"]["executionFailed"], 1)
        self.assertFalse(summary["documents"][1]["detailAvailable"])


if __name__ == "__main__":
    unittest.main()

